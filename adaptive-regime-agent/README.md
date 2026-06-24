# Adaptive Regime AI Agent

A live, signal-only **AI agent** for BTC perpetual futures. Every scheduled
cycle it assembles a fresh market briefing from managed data and asks a bounded
language model to reason over it like a disciplined analyst — then emits a
long / short / close / flat signal **with the reasoning attached**.

This is a live-only agent (`runtime_profile: llm_bounded`,
`backtest_support: none`): open-ended model reasoning cannot be faithfully
replayed on historical data, so it carries **paper / live evidence, not a
backtest**. It is the agentic counterpart to the deterministic, backtested
`adaptive-market-regime` Playbook.

## 策略 / Strategy

The thesis is that the hard part of futures trading is not any single
indicator — it is *synthesizing* conflicting signals into one coherent view.
Each cycle the agent computes a price-regime read (trend alignment, efficiency
of travel, volatility, distance from the rolling mean) and, when available,
funding-rate behavior, open-interest shifts, and crowd positioning. That
briefing is handed to the model, which weighs the evidence and returns a
decision plus a confidence score and a written rationale.

## 开仓 / Entry

The agent opens **long** only when the evidence it is shown leans bullish on
balance, and **short** only when it leans bearish. It is explicitly instructed
to prefer a **flat** stance when the picture is mixed, so "no trade" is a normal
output. Every signal carries a confidence level so subscribers can size or
ignore it.

## 平仓 / Exit

The agent is prompted to **close** or stand aside when its own thesis weakens,
when positioning looks crowded against it, when funding makes holding
expensive, or when an extended move shows exhaustion. Because it re-decides from
scratch each cycle, a later "flat" or opposite call is itself the exit.

## Parameters

- **trading_symbols** — the supported pair to analyze (default BTCUSDT).
- **risk_appetite** — `conservative` / `balanced` / `aggressive`. Shifts the
  agent between cautious and assertive behavior; higher appetite produces more
  frequent, higher-conviction calls and therefore more exposure.
- **lookback_hours** — how much recent history the agent reviews before
  deciding. Longer lookbacks emphasize the larger trend; shorter ones react
  faster to recent moves.

## Honest data note

Funding, open-interest, and positioning inputs are best-effort. If one is
unavailable for a cycle, it is reported to the model as missing and listed in
the signal `meta.missing_inputs` — values are never fabricated to fill a gap.

## 风险 / Risk

Language models can be confidently wrong. Regimes can break faster than any
briefing captures, and the agent has **no historical backtest** to lean on.
Live execution pays fees and slippage, and crowded or thin conditions can hurt.
Treat each signal as one analyst's opinion under uncertainty, never as a
guarantee — and only act with capital you can afford to lose.
