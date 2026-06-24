# BTC Range Reversion Scalper

A mean-reversion Playbook on BTC perpetual futures. It fades statistical
extremes **inside ranges** and exits when price reverts to its average,
producing many small, frequent wins — with a wide stop to contain the rarer
losing trades when a range breaks.

## 策略 / Strategy

Markets spend a large share of the time oscillating inside a range rather than
trending. Inside a range, price repeatedly stretches away from its recent
average and snaps back. This strategy harvests that snap-back. It only arms
itself when a regime filter reads the market as sideways (price churning rather
than travelling efficiently in one direction).

## 开仓 / Entry

When the market is ranging, the Playbook opens a **long** after price stretches
unusually far below its recent average, and a **short** after it stretches
unusually far above it — treating the extreme as an overshoot likely to correct.

## 平仓 / Exit

A position is closed as soon as price reverts back toward its average (a small,
frequent win). Each trade also carries a **wide protective stop** and a **time
limit**: if a range breaks into a real trend, the loss is contained and capital
is freed instead of held in hope. The result is many small wins and a smaller
number of larger, controlled losses.

## Parameters

- **leverage** — amplifies both the steady gains and the occasional drawdowns;
  it does not make the strategy more selective.
- **margin_budget** — per-strategy capital the platform sizes against and uses
  as the denominator for return %. Lower it to take smaller positions.

The internals (z-score window and entry/exit thresholds, the ranging filter, the
ATR stop multiple, the time stop) are published in `strategy_config` for
transparency but are not user-editable.

## How to read the metrics

Win rate is high **by design** — exiting at the mean realizes most trades as
small winners. Judge it alongside **profit factor** and **max drawdown**: the
loss profile is asymmetric, so a single trend-break loss can equal many wins.

## 风险 / Risk

The strategy underperforms when a range breaks decisively into a sustained
trend, when volatility expands sharply, or around gap-driven news — a faded
extreme can keep extending against the position until the stop is hit. A high
historical win rate is **not** a promise of profit. Past backtest performance
never guarantees future results; only subscribe with risk you can afford to lose.
