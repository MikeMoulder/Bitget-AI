# Adaptive Market Regime

An adaptive, regime-switching Playbook on BTC perpetual futures. One engine,
three behaviors: it trend-follows when the market is genuinely trending,
mean-reverts when the market is ranging, and stays flat when the regime is
unclear. It runs on 1-hour bars.

## 策略 / Strategy

The core idea is that no single edge works in every market, so the strategy
first measures how *efficiently* price is travelling and uses that to classify
the current environment before deciding how to trade. A high efficiency of
travel means a clean directional trend; a low efficiency means choppy,
range-bound conditions; everything in between is treated as unclear. The
strategy adapts its entire stance to that classification instead of forcing one
style onto every condition.

## 开仓 / Entry

- **Trending regime** — the Playbook opens a long when shorter-horizon momentum
  is aligned above the longer-horizon trend, and opens a short when that
  alignment points down. It rides the move rather than fighting it.
- **Ranging regime** — the Playbook inverts its instinct and fades stretch: it
  opens a long after price extends unusually far below its rolling center, and
  opens a short after price extends unusually far above it, betting on a return
  toward the mean.
- **Unclear regime** — no new position is opened.

## 平仓 / Exit

- A **trend** position is closed when momentum alignment fades or the regime
  stops qualifying as a trend.
- A **range** position is closed once price reverts back toward its rolling
  center, or the market shifts out of the ranging regime.
- Whenever the classifier reads conditions as unclear, any open exposure is
  reduced to flat.
- Every trade also carries a volatility-based stop. Trend trades use a trailing
  stop that ratchets in the trade's favor; reversion trades use a fixed stop and
  target a return toward the rolling center. A short cooldown after each exit
  reduces back-to-back whipsaw entries.

## Parameters

Subscribers may tune:

- **trading_symbols** — the supported pair to trade (default BTCUSDT).
- **leverage** — amplifies both upside and drawdown equally. Higher leverage
  does not make the strategy more selective; it only sizes risk larger.
- **margin_budget** — per-strategy capital cap. The platform sizes orders
  against it and uses it as the denominator for the user-facing return
  percentage.

The regime internals (trend horizons, the efficiency-ratio thresholds that
separate trend / range / unclear, the mean-reversion entry and exit bands, the
ATR-based stop/trailing multiples, the per-trade risk target used for
volatility-based sizing, and the post-exit cooldown) are published in
`strategy_config` for transparency but are not user-editable. Position size is
set so each trade risks roughly a constant amount to its stop, so the strategy
takes smaller size when volatility is high and larger size when it is low.

## How To Read Backtest Metrics

The backtest reports `total_return_pct`, `sharpe_ratio`, `max_drawdown_pct`,
`win_rate`, and `total_trades`. `total_return_pct` is the strategy-budget return
(`net_pnl / margin_budget`); `account_total_return_pct` is the raw account-level
number from the replay engine. Read drawdown depth and trade count alongside
return — a high return on too few trades is not robust evidence.

## 风险 / Risk

This strategy underperforms when regimes change faster than the classifier can
confirm them, producing whipsaw losses at the boundary between trend and range.
Sudden gap-driven moves around major news, thin liquidity, and persistent
funding-rate dislocation can also hurt it. Live execution pays slippage and
exchange fees on every entry and exit. Past historical performance is not a
guarantee of live profitability — match this Playbook against your own risk
tolerance, and do not run it with leverage you cannot afford to draw down.
