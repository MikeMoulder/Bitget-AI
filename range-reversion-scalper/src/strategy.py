"""BTC Range Reversion Scalper — Nautilus strategy.

Mean-reversion that only trades when the market is ranging, enters at a
statistical extreme, and exits when price reverts to the mean. Because most
reversions reach the mean before the (wide) stop is hit, the win rate is high;
the trade-off is occasional larger losing trades when a range breaks into a
trend — handled by the ranging filter and the ATR stop.

Self-contained (no local imports): the backtest runner imports this module
directly as ``strategy``.
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


class RangeReversionConfig(StrategyConfig):
    instrument_id: Optional[InstrumentId] = None
    bar_type: Optional[BarType] = None
    instrument_ids: tuple[InstrumentId, ...] = ()
    bar_types: tuple[BarType, ...] = ()
    trade_size: str = "0.01"
    z_period: int = 30          # rolling window for mean / std (z-score)
    z_entry: float = 2.0        # enter when |z| >= this (statistical extreme)
    exit_z: float = 0.25        # exit when |z| <= this (reverted to mean)
    er_period: int = 24         # efficiency-ratio window (regime detector)
    er_range_max: float = 0.35  # only trade when ER <= this (i.e. ranging)
    atr_period: int = 14
    atr_stop_mult: float = 3.0  # wide protective stop (in ATRs)
    max_hold_bars: int = 48     # time-stop: bail if it never reverts


class RangeReversionStrategy(Strategy):
    def __init__(self, config: RangeReversionConfig) -> None:
        super().__init__(config)
        self.cfg = config
        self._closes: list[float] = []
        self._atr: Optional[float] = None
        self._prev_close: Optional[float] = None
        self._position: str = "NONE"          # NONE / LONG / SHORT
        self._stop_price: Optional[float] = None
        self._bars_in_trade: int = 0
        self._instrument: Optional[Instrument] = None

    def on_start(self) -> None:
        bar_type = self.cfg.bar_type or (self.cfg.bar_types[0] if self.cfg.bar_types else None)
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

    def on_bar(self, bar: Bar) -> None:
        high, low, close = float(bar.high), float(bar.low), float(bar.close)
        self._closes.append(close)
        self._update_atr(high, low, close)
        self._prev_close = close

        warmup = max(self.cfg.z_period, self.cfg.er_period, self.cfg.atr_period) + 2
        if len(self._closes) < warmup or not self._atr or self._atr <= 0:
            return

        instrument = self._instrument
        if instrument is None:
            return

        z = self._zscore()

        # --- Manage an open position (exit at mean = win, or wide stop = loss) ---
        if self._position != "NONE":
            self._bars_in_trade += 1
            hit_stop = (
                (self._position == "LONG" and close <= (self._stop_price or -1))
                or (self._position == "SHORT" and close >= (self._stop_price or 1e18))
            )
            reverted = (
                (self._position == "LONG" and z >= -self.cfg.exit_z)
                or (self._position == "SHORT" and z <= self.cfg.exit_z)
            )
            timed_out = self._bars_in_trade >= self.cfg.max_hold_bars
            if hit_stop or reverted or timed_out:
                self._flatten(instrument)
            return

        # --- Entry: only when ranging, at a statistical extreme ---
        if self._classify_ranging():
            qty = Quantity(Decimal(self.cfg.trade_size), instrument.size_precision)
            if z <= -self.cfg.z_entry:
                self._open("LONG", instrument, qty, close - self.cfg.atr_stop_mult * self._atr)
            elif z >= self.cfg.z_entry:
                self._open("SHORT", instrument, qty, close + self.cfg.atr_stop_mult * self._atr)

    # ------------------------------------------------------------------ #
    def _classify_ranging(self) -> bool:
        n = self.cfg.er_period
        w = self._closes[-(n + 1):]
        direction = abs(w[-1] - w[0])
        volatility = sum(abs(w[i] - w[i - 1]) for i in range(1, len(w)))
        er = direction / volatility if volatility > 0 else 0.0
        return er <= self.cfg.er_range_max

    def _zscore(self) -> float:
        w = np.asarray(self._closes[-self.cfg.z_period:], dtype=float)
        std = float(w.std())
        return 0.0 if std <= 0 else (w[-1] - float(w.mean())) / std

    def _update_atr(self, high: float, low: float, close: float) -> None:
        tr = high - low if self._prev_close is None else max(
            high - low, abs(high - self._prev_close), abs(low - self._prev_close)
        )
        if self._atr is None:
            self._atr = tr
        else:
            p = self.cfg.atr_period
            self._atr = (self._atr * (p - 1) + tr) / p

    # ------------------------------------------------------------------ #
    def _open(self, direction: str, instrument: Instrument, qty: Quantity, stop: float) -> None:
        side = OrderSide.BUY if direction == "LONG" else OrderSide.SELL
        self._submit(instrument.id, side, qty)
        self._position = direction
        self._stop_price = stop
        self._bars_in_trade = 0

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
        self._stop_price = None
        self._bars_in_trade = 0
