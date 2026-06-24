# Backtest evidence — adaptive-market-regime

Backtests were run in the GetAgent managed sandbox via the documented control
plane (`POST /api/v1/playbook/run`) on real Bitget BTCUSDT 1h data. All metrics
below are the platform's **official strategy-basis** figures
(`net_pnl / margin_budget`), i.e. the numbers shown on the Playbook card — not
hand-written. The strategy code that produces them is in [`src/`](src/).

## v0.1.0 → v0.2.0 (published)

The honest story here is **risk-adjusted improvement**, not a flashy win rate.
v0.1.0 was a clean baseline (regime switch, no stops, fixed size). v0.2.0 added
volatility-targeted sizing, ATR stop-loss + trailing stop, a macro-trend filter,
and a post-exit cooldown.

| Metric | v0.1.0 | v0.2.0 | Read |
|---|---|---|---|
| Total return % (strategy basis) | −0.018% | **+0.002%** | flipped positive (both ~flat) |
| Sharpe ratio | −2.38 | **+0.17** | negative → positive — the real win |
| Max drawdown % | 30.25% | **18.37%** | risk cut ~40% |
| Win rate | 46.2% | 42.1% | lower (trend trades win less often, win bigger) |
| Profit factor | 1.081 | 0.992 | ~break-even |
| Total trades | 130 | **38** | whipsaw churn removed |
| Margin budget | 200 | 300 USDT | — |

**Interpretation:** v0.2.0 is roughly break-even but materially more robust —
Sharpe went from deeply negative to slightly positive and drawdown dropped ~40%
while trade count fell from 130 to 38. We did **not** select a flattering
window; this is a long, mixed-regime replay.

## Reproduce

1. `python3 /root/.claude/skills/getagent/scripts/validate.py adaptive-market-regime/` → `Validation PASSED`
2. Package: `tar czf amr.tar.gz -C adaptive-market-regime .`
3. `POST /api/v1/playbook/upload` (multipart, `ACCESS-KEY` header) → `draft_id`
4. `POST /api/v1/playbook/run {"version_id": "<draft_id>"}` → poll `GET /api/v1/playbook/run?run_id=...`
5. Read `metrics_output` (strategy basis) from the completed run.

The replay window, symbol, and instrument are declared in
[`backtest.yaml`](backtest.yaml); strategy logic is in
[`src/strategy.py`](src/strategy.py).
