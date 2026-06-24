# Adaptive Regime AI Agent (Layer B)

A custom AI trading agent that **perceives → decides → acts** on Bitget BTC
perpetual futures (DEMO / paper trading).

- **Brain:** `google/gemini-3.1-flash-lite` via **OpenRouter** (swap with `OPENROUTER_MODEL`).
- **Hands:** the official **Bitget MCP server** (`bitget-mcp-server`, 23 tools) — bridged
  over stdio, paper-trading mode (`paptrading: 1`).
- **Guardrails:** the bridge enforces hard risk caps (allowed symbols, max order
  size, max leverage) that the model physically cannot exceed.

This is the agentic counterpart to the published GetAgent Playbooks
(`adaptive-market-regime`, `adaptive-regime-agent`). It's the "only an AI agent
can do this" piece — an LLM reasoning over live market data and trading through a
real exchange API.

## How it works

```
OpenRouter (gemini-3.1-flash-lite)  ── manual tool-use loop ──┐
   PERCEIVE  futures_get_candles / funding_rate / open_interest / ticker / positions
   DECIDE    classify regime (trend / range / unclear) under a risk appetite
   ACT       futures_place_order / futures_set_leverage  (paper, risk-capped)
                       │
              lib/bitget-mcp.ts  ──spawns──▶  bitget-mcp-server (stdio, --paper-trading)
```

`lib/` is framework-agnostic so the Next.js dashboard (Phase 2) imports it directly.

## Setup

```bash
npm install
cp .env.example .env   # fill in keys
```

Required: `OPENROUTER_API_KEY` (get one at openrouter.ai).
For live paper orders also set Bitget **DEMO** keys (`BITGET_API_KEY`,
`BITGET_SECRET_KEY`, `BITGET_PASSPHRASE`) — create at bitget.com → API Management
with Read + Trade, using a demo key.

## Run

```bash
npm run tools            # smoke test: list the 23 MCP tools (no keys needed)
npm run agent            # DRY RUN — perceive + decide + propose an order, place nothing
npm run agent -- --live  # place PAPER orders on the demo account (needs Bitget demo keys)
```

`npm run tools` works with zero credentials and verifies the MCP bridge.
`npm run agent` (dry run) needs only `OPENROUTER_API_KEY`.

## Risk caps (enforced in `lib/bitget-mcp.ts`, not just prompted)

| Env | Default | Meaning |
|---|---|---|
| `AGENT_ALLOWED_SYMBOLS` | `BTCUSDT` | Only these symbols may be traded |
| `AGENT_MAX_ORDER_SIZE` | `0.01` | Max contracts per order |
| `AGENT_MAX_LEVERAGE` | `3` | Max leverage the agent may set |
| `AGENT_RISK_APPETITE` | `balanced` | `conservative` / `balanced` / `aggressive` |

Any tool call that exceeds a cap is rejected by the bridge before reaching Bitget.

## Layout

| Path | Purpose |
|---|---|
| `lib/bitget-mcp.ts` | Spawn + bridge the Bitget MCP server; enforce risk caps |
| `lib/agent.ts` | OpenRouter perceive→decide→act tool-use loop (emits events) |
| `lib/config.ts` | Env / credential loading |
| `bin/list-tools.ts` | `npm run tools` smoke test |
| `bin/agent.ts` | `npm run agent` CLI runner |

## Roadmap

- **Phase 2 — Web UI (Next.js + React):** dashboard streaming the agent's
  reasoning, tool calls, positions, and P&L; `lib/` drops in behind API routes.
- **Phase 2 — Telegram:** push each decision + fill.
- **Phase 3 — Perception Skills:** wire in the Bitget Skill Hub analyst skills
  (macro, sentiment, technicals, on-chain, news) for richer context.
