"""Adaptive market-regime Nautilus strategy (v2).

Self-contained (no local imports) because the backtest runner imports this
module directly as ``strategy``.

Improvements over v1:
- Volatility-targeted position sizing (constant ~USDT risk per trade via ATR).
- ATR stop-loss + trailing stop on trend trades; fixed stop + mean target on
  reversion trades.
- Tighter regime gating with a wide "unclear" dead zone, plus a post-exit
  cooldown to stop whipsaw churn.
- Higher-timeframe (macro EMA) bias filter: trend trades must agree with the
  macro slope; reversion trades are skipped when the macro trend is strong.

Regimes:
- TREND   -> trend-follow in the direction of moving-average alignment
- RANGE   -> mean-revert against stretch away from a rolling center (z-score)
- UNCLEAR -> hold no position
"""
from decimal import Decimal
from typing import Optional

import numpy as np
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy


class AdaptiveRegimeStrategyConfig(StrategyConfig):
    instrument_id: Optional[InstrumentId] = None
    bar_type: Optional[BarType] = None
    instrument_ids: tuple[InstrumentId, ...] = ()
    bar_types: tuple[BarType, ...] = ()
    # regime detection
    trend_fast: int = 20
    trend_slow: int = 50
    macro_period: int = 200
    er_period: int = 24
    er_trend_threshold: float = 0.52
    er_range_threshold: float = 0.16
    z_period: int = 24
    z_entry: float = 1.8
    z_exit: float = 0.4
    macro_bias_z: float = 1.0      # skip reversion when |macro stretch| beyond this
    # risk / sizing
    atr_period: int = 14
    atr_stop_mult: float = 2.5     # trend stop distance in ATRs
    atr_trail_mult: float = 3.0    # trend trailing distance in ATRs
    mr_stop_mult: float = 2.0      # reversion stop distance in ATRs
    risk_per_trade: float = 12.0   # target USDT risk per trade
    min_qty: float = 0.001
    max_qty: float = 0.05
    cooldown_bars: int = 6


class AdaptiveRegimeStrategy(Strategy):
    def __init__(self, config: AdaptiveRegimeStrategyConfig) -> None:
        super().__init__(config)
        self.cfg = config
        self._closes: list[float] = []
        self._fast_ema: Optional[float] = None
        self._slow_ema: Optional[float] = None
        self._macro_ema: Optional[float] = None
        self._atr: Optional[float] = None
        self._prev_close: Optional[float] = None
        self._position: str = "NONE"          # NONE / LONG / SHORT
        self._entry_regime: Optional[str] = None
        self._stop: Optional[float] = None     # active stop price
        self._cooldown: int = 0
        self._instrument: Optional[Instrument] = None

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def on_start(self) -> None:
        bar_type = self.cfg.bar_type or (
            self.cfg.bar_types[0] if self.cfg.bar_types else None
        )
        instrument_id = self.cfg.instrument_id or (
            self.cfg.instrument_ids[0] if self.cfg.instrument_ids else None
        )
        if bar_type is None or instrument_id is None:
            raise RuntimeError("bar_type and instrument_id must be set")
        self._instrument = self.cache.instrument(instrument_id)
        self.subscribe_bars(bar_type)

    def on_stop(self) -> None:
        if self._instrument is not None:
            self.cancel_all_orders(self._instrument.id)
            self.close_all_positions(self._instrument.id)

    # ------------------------------------------------------------------ #
    # Core loop
    # ------------------------------------------------------------------ #
    def on_bar(self, bar: Bar) -> None:
        high, low, close = float(bar.high), float(bar.low), float(bar.close)
        self._closes.append(close)
        self._update_atr(high, low, close)
        self._prev_close = close

        self._fast_ema = self._ema(self._fast_ema, close, self.cfg.trend_fast)
        self._slow_ema = self._ema(self._slow_ema, close, self.cfg.trend_slow)
        self._macro_ema = self._ema(self._macro_ema, close, self.cfg.macro_period)

        if self._cooldown > 0:
            self._cooldown -= 1

        warmup = max(self.cfg.macro_period, self.cfg.er_period,
                     self.cfg.z_period, self.cfg.atr_period) + 2
        if len(self._closes) < warmup or not self._atr or self._atr <= 0:
            return

        instrument = self._instrument
        if instrument is None:
            return

        # --- Manage an open position first (stops + regime exits) ------- #
        if self._position != "NONE":
            if self._hit_stop(close):
                self._flatten(instrument)
            else:
                self._maybe_regime_exit(instrument, close)
            if self._position != "NONE":
                self._update_trailing_stop(close)
                return  # one action per bar while in a trade

        # --- Entry logic ------------------------------------------------ #
        if self._position == "NONE" and self._cooldown == 0:
            self._maybe_enter(instrument, close)

    # ------------------------------------------------------------------ #
    # Entries / exits
    # ------------------------------------------------------------------ #
    def _maybe_enter(self, instrument: Instrument, close: float) -> None:
        regime = self._classify_regime()
        z = self._zscore()
        macro_z = self._macro_stretch(close)
        trend_dir = "LONG" if (self._fast_ema or 0) >= (self._slow_ema or 0) else "SHORT"
        macro_up = close >= (self._macro_ema or close)

        if regime == "TREND":
            # trend trades must agree with the macro slope
            if (trend_dir == "LONG") != macro_up:
                return
            stop_dist = self.cfg.atr_stop_mult * self._atr
            qty = self._size(stop_dist, instrument)
            if qty is None:
                return
            if trend_dir == "LONG":
                self._open("LONG", "TREND", instrument, qty, close - stop_dist)
            else:
                self._open("SHORT", "TREND", instrument, qty, close + stop_dist)

        elif regime == "RANGE":
            # don't fade into a strong macro trend
            if abs(macro_z) >= self.cfg.macro_bias_z:
                return
            stop_dist = self.cfg.mr_stop_mult * self._atr
            qty = self._size(stop_dist, instrument)
            if qty is None:
                return
            if z <= -self.cfg.z_entry:
                self._open("LONG", "RANGE", instrument, qty, close - stop_dist)
            elif z >= self.cfg.z_entry:
                self._open("SHORT", "RANGE", instrument, qty, close + stop_dist)
        # UNCLEAR -> stay flat

    def _maybe_regime_exit(self, instrument: Instrument, close: float) -> None:
        regime = self._classify_regime()
        if self._entry_regime == "TREND":
            trend_dir = "LONG" if (self._fast_ema or 0) >= (self._slow_ema or 0) else "SHORT"
            if regime != "TREND" or trend_dir != self._position:
                self._flatten(instrument)
        elif self._entry_regime == "RANGE":
            if abs(self._zscore()) <= self.cfg.z_exit or regime == "TREND":
                self._flatten(instrument)

    # ------------------------------------------------------------------ #
    # Stop management
    # ------------------------------------------------------------------ #
    def _hit_stop(self, close: float) -> bool:
        if self._stop is None:
            return False
        if self._position == "LONG":
            return close <= self._stop
        if self._position == "SHORT":
            return close >= self._stop
        return False

    def _update_trailing_stop(self, close: float) -> None:
        if self._entry_regime != "TREND" or self._stop is None or not self._atr:
            return
        trail = self.cfg.atr_trail_mult * self._atr
        if self._position == "LONG":
            self._stop = max(self._stop, close - trail)
        elif self._position == "SHORT":
            self._stop = min(self._stop, close + trail)

    # ------------------------------------------------------------------ #
    # Indicators
    # ------------------------------------------------------------------ #
    def _classify_regime(self) -> str:
        n = self.cfg.er_period
        window = self._closes[-(n + 1):]
        direction = abs(window[-1] - window[0])
        volatility = sum(abs(window[i] - window[i - 1]) for i in range(1, len(window)))
        er = direction / volatility if volatility > 0 else 0.0
        if er >= self.cfg.er_trend_threshold:
            return "TREND"
        if er <= self.cfg.er_range_threshold:
            return "RANGE"
        return "UNCLEAR"

    def _zscore(self) -> float:
        n = self.cfg.z_period
        window = np.asarray(self._closes[-n:], dtype=float)
        mean = float(window.mean())
        std = float(window.std())
        return 0.0 if std <= 0 else (window[-1] - mean) / std

    def _macro_stretch(self, close: float) -> float:
        n = self.cfg.macro_period
        window = np.asarray(self._closes[-n:], dtype=float)
        std = float(window.std())
        macro = self._macro_ema or float(window.mean())
        return 0.0 if std <= 0 else (close - macro) / std

    def _update_atr(self, high: float, low: float, close: float) -> None:
        if self._prev_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))
        if self._atr is None:
            self._atr = tr
        else:
            p = self.cfg.atr_period
            self._atr = (self._atr * (p - 1) + tr) / p  # Wilder smoothing

    @staticmethod
    def _ema(prev: Optional[float], value: float, period: int) -> float:
        if prev is None:
            return value
        alpha = 2.0 / (period + 1)
        return alpha * value + (1.0 - alpha) * prev

    # ------------------------------------------------------------------ #
    # Sizing / order helpers
    # ------------------------------------------------------------------ #
    def _size(self, stop_dist: float, instrument: Instrument) -> Optional[Quantity]:
        if stop_dist <= 0:
            return None
        raw = self.cfg.risk_per_trade / stop_dist
        raw = max(self.cfg.min_qty, min(self.cfg.max_qty, raw))
        qty = Quantity(Decimal(str(round(raw, instrument.size_precision))),
                       instrument.size_precision)
        return qty if float(qty) > 0 else None

    def _open(self, direction: str, regime: str, instrument: Instrument,
              qty: Quantity, stop: float) -> None:
        side = OrderSide.BUY if direction == "LONG" else OrderSide.SELL
        self._submit(instrument.id, side, qty)
        self._position = direction
        self._entry_regime = regime
        self._stop = stop

    def _submit(self, instrument_id: InstrumentId, side: OrderSide, quantity: Quantity) -> None:
        order = self.order_factory.market(
            instrument_id=instrument_id,
            order_side=side,
            quantity=quantity,
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)

    def _flatten(self, instrument: Instrument) -> None:
        close_side = OrderSide.SELL if self._position == "LONG" else OrderSide.BUY
        for position in self.cache.positions_open(instrument_id=instrument.id):
            self._submit(instrument.id, close_side, position.quantity)
        self._position = "NONE"
        self._entry_regime = None
        self._stop = None
        self._cooldown = self.cfg.cooldown_bars
