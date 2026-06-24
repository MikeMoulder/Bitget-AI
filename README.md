# Adaptive Regime — AI Trading Agent for Bitget

**Bitget AI Base Camp Hackathon S1 · Track 1 (Trading Agent)**

An AI agent that **perceives** market conditions, **decides** under an adaptive
market-regime thesis, and **acts** (paper trading) on Bitget BTC perpetual
futures — plus two published GetAgent Playbooks as backtested / live-signal
counterparts.

> **Core thesis:** no single edge works in every market. Trend-follow when the
> market is trending, mean-revert when it's ranging, and stay flat when it's
> unclear. The hard part isn't any one indicator — it's *classifying the regime*
> and synthesizing conflicting signals (price action, funding, open interest,
> positioning) into one decision. That synthesis is exactly what an AI agent can
> do that rule-based quant cannot.

## What's in this repo

| Path | What it is | Evidence |
|---|---|---|
| [`regime-agent/`](regime-agent/) | **Live AI agent** — `google/gemini-3.1-flash-lite` (via OpenRouter) driving the official **Bitget Agent Hub MCP** (paper trading) in a perceive→decide→act loop. | [Live run log](regime-agent/runs/2026-06-24-btcusdt-cycle.md) |
| [`adaptive-market-regime/`](adaptive-market-regime/) | **Deterministic, backtested** regime-switch strategy (GetAgent Playbook, published). Trend + mean-reversion + ATR stops + volatility-targeted sizing. | [Backtest + metrics](adaptive-market-regime/BACKTEST.md) (reproducible via the package code) |
| [`adaptive-regime-agent/`](adaptive-regime-agent/) | **LLM-assisted live-signal** GetAgent Playbook (published) — bounded LLM reasoning over regime/funding/OI, signal-only. | Published on the Playbook explore page |
| [`range-reversion-scalper/`](range-reversion-scalper/) | Experiment: mean-reversion scalper. Honestly **net-negative** over the tested window — kept as a documented negative result, not published. | — |
| [`SUBMISSION.md`](SUBMISSION.md) | Project description (4-part) for the hackathon form. | — |

## The agent (Layer B) — quick start

```bash
cd regime-agent
npm install
cp .env.example .env        # add OPENROUTER_API_KEY
npm run tools               # smoke test: lists the 23 Bitget MCP tools (no keys)
npm run agent               # dry run: perceive → decide → propose (needs OPENROUTER_API_KEY)
npm run agent -- --live     # place PAPER orders (needs Bitget DEMO keys)
```

The agent calls the Bitget MCP read tools for **real** market data, classifies
the regime, and emits a decision with a written rationale. Write tools are
guarded by hard risk caps (allowed symbols, max order size, max leverage)
enforced in [`regime-agent/lib/bitget-mcp.ts`](regime-agent/lib/bitget-mcp.ts) —
the model physically cannot exceed them.

## Architecture

```
                 ┌─────────────────────────────────────────────────────────┐
LAYER A (Bitget-hosted GetAgent Playbooks — backtest / live-signal evidence) │
  • adaptive-market-regime   deterministic, backtested, published            │
  • adaptive-regime-agent    llm_bounded live signals, published             │
                 └─────────────────────────────────────────────────────────┘
                 ┌─────────────────────────────────────────────────────────┐
LAYER B (self-hosted agent — the product)                                   │
   Gemini 3.1 Flash Lite (OpenRouter)                                        │
     PERCEIVE  Bitget MCP: candles · funding · open interest · positions     │
     DECIDE    regime = trend / range / unclear  →  long / short / flat      │
     ACT       futures_place_order / set_leverage  (paper, risk-capped)      │
                 └─────────────────────────────────────────────────────────┘
```

## Honest self-assessment

- The **live agent** is the strongest piece: it genuinely runs end-to-end on
  real Bitget data and produces reasoned decisions — something only an LLM agent
  does. (Brain is `gemini-3.1-flash-lite` for cost; swappable via `OPENROUTER_MODEL`.)
- The **deterministic backtest** is an honest, risk-managed baseline — roughly
  break-even on a long window. We did **not** cherry-pick a flattering window to
  inflate the numbers. See [`adaptive-market-regime/BACKTEST.md`](adaptive-market-regime/BACKTEST.md).
- The **scalper experiment** is included as a negative result rather than hidden.

Built with the Bitget Agent Hub (`bitget-mcp-server`) and GetAgent
(`@bitget-ai/getagent-skill`).
