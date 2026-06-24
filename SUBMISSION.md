# Project Submission — Adaptive Regime AI Trading Agent

**Hackathon:** Bitget AI Base Camp S1
**Track:** 🟦 Track 1 — Trading Agent
**Bitget UID:** _<fill in your registered UID>_
**Repo:** https://github.com/MikeMoulder/bitget-ai
**Team:** MikeMoulder

---

## 1. What we built

An AI trading agent for Bitget BTC perpetual futures that closes the full loop —
**perceive → decide → act → manage risk** — with no human in the middle, plus
two published GetAgent Playbooks that serve as its backtested and live-signal
counterparts.

- **Live agent (`regime-agent/`):** a TypeScript app where
  `google/gemini-3.1-flash-lite` (via OpenRouter) drives the official **Bitget
  Agent Hub MCP server** in a tool-use loop. Each cycle it pulls real market
  data (candles, funding rate, open interest, positions), classifies the market
  regime, decides long / short / flat, and — in live mode — places **paper
  orders** on the Bitget demo account. Hard risk caps (allowed symbols, max
  order size, max leverage) are enforced in the harness, not just the prompt.
- **`adaptive-market-regime` (published Playbook):** a deterministic,
  backtestable regime-switch strategy (trend-following + mean-reversion + ATR
  stops + volatility-targeted sizing).
- **`adaptive-regime-agent` (published Playbook):** a live-signal,
  LLM-assisted Playbook that reasons over regime/funding/positioning each cycle.

## 2. Core logic / thesis

The central assumption is that **no single edge works in every market**, so the
agent's first job is to *classify the regime* before choosing a tactic:

- **Trending** → trade in the direction of momentum (trend-following), ride the
  move with a trailing stop.
- **Ranging** → fade statistical extremes back toward the mean (mean-reversion).
- **Unclear** → stay flat; cash is a position.

Regime is detected from how *efficiently* price is travelling (a Kaufman
efficiency-ratio style measure) plus moving-average alignment. The genuinely
hard, agent-suited part is **synthesis**: weighing price action against funding
(is holding expensive?), open-interest shifts, and crowd positioning, then
committing to a single decision with a confidence and a written rationale.
Deterministic quant can encode one rule; an LLM agent can weigh conflicting,
unstructured signals the way a discretionary trader does — that's the bet.

## 3. How to run it & evidence (runnability)

**Live agent — reproducible by any judge:**

```bash
cd regime-agent && npm install && cp .env.example .env   # add OPENROUTER_API_KEY
npm run agent          # dry run: real Bitget data → regime → decision (no order)
npm run agent -- --live  # paper orders on the Bitget demo account (needs demo keys)
```

- **Verifiable run record:** [`regime-agent/runs/2026-06-24-btcusdt-cycle.md`](regime-agent/runs/2026-06-24-btcusdt-cycle.md)
  — a real cycle: the agent fetched BTC at ~$62,814, funding −0.000002, OI
  ~57,523 BTC, classified the regime as ranging/unclear, and chose **flat** with
  a written verdict.
- **Backtest with code:** [`adaptive-market-regime/`](adaptive-market-regime/)
  is a complete, reproducible Playbook package; metrics and the v1→v2
  improvement are documented in [`adaptive-market-regime/BACKTEST.md`](adaptive-market-regime/BACKTEST.md).
  Judges can reproduce by uploading the package via the GetAgent API and running
  `/api/v1/playbook/run`.
- **Published Playbooks:** both `adaptive-market-regime` and
  `adaptive-regime-agent` are live on the Bitget Playbook explore page under our UID.

**Honest self-assessment.** The agent is the centerpiece and genuinely runs; the
deterministic strategy is an honest, risk-managed baseline that is ~break-even
on a long, *un-cherry-picked* window (we improved Sharpe and halved drawdown
from v1 → v2 rather than chase a flattering win-rate number). A mean-reversion
scalper experiment was net-negative over the tested window and is included as a
documented negative result rather than hidden.

## 4. Our take on AI trading (optional)

Rule-based quant is brittle precisely where markets are interesting — at regime
boundaries, around news, when funding and positioning contradict price. The
opportunity for AI agents isn't a magically higher win rate; it's **judgment
under ambiguity and transparency of reasoning**: an agent can read many noisy
signals, explain *why* it's taking (or skipping) a trade, and adapt its tactic
to the regime. The win-rate column on a marketplace is the most gameable number
in trading; we deliberately optimized for honest, reproducible, risk-managed
behavior and a real agentic loop instead.
