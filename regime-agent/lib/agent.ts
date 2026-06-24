/**
 * Adaptive Regime trading agent loop.
 *
 * Brain: google/gemini-3.1-flash-lite via OpenRouter (OpenAI-compatible API).
 * Swap the model with OPENROUTER_MODEL — any OpenRouter model with tool/function
 * calling works.
 *
 * One cycle = perceive → decide → act:
 *   - PERCEIVE: the model calls Bitget read tools (candles, funding, open
 *     interest, ticker, positions) to build a live picture of BTC.
 *   - DECIDE: it classifies the regime (trend / range / unclear) and reasons
 *     about positioning under the configured risk appetite.
 *   - ACT: it either places a paper order / sets leverage (guarded by the
 *     bridge risk caps) or holds, and explains why.
 *
 * Implemented as a manual OpenAI-style tool-use loop so the harness can gate
 * writes, log every step, and stream events to a UI.
 */
import OpenAI from "openai";
import type { BitgetBridge, McpTool } from "./bitget-mcp.js";

export type AgentEvent =
  | { kind: "text"; text: string }
  | { kind: "tool_call"; name: string; input: unknown }
  | { kind: "tool_result"; name: string; ok: boolean; text: string }
  | { kind: "done"; finalText: string; placedOrders: number };

export interface AgentConfig {
  symbol: string;
  riskAppetite: "conservative" | "balanced" | "aggressive";
  /** If true, the agent only analyzes and proposes — it must not call write tools. */
  dryRun: boolean;
  maxIterations?: number;
}

const DEFAULT_MODEL = "google/gemini-3.1-flash-lite";

/**
 * Gemini's function-calling validator is stricter than Anthropic's. Strip schema
 * keywords it rejects (`$schema`, `additionalProperties`, `$ref`, etc.) and make
 * sure every tool exposes a plain object schema.
 */
function sanitizeSchema(schema: unknown): Record<string, unknown> {
  const drop = new Set(["$schema", "additionalProperties", "$ref", "$defs", "definitions"]);
  const walk = (node: unknown): unknown => {
    if (Array.isArray(node)) return node.map(walk);
    if (node && typeof node === "object") {
      const out: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(node as Record<string, unknown>)) {
        if (drop.has(k)) continue;
        out[k] = walk(v);
      }
      return out;
    }
    return node;
  };
  const cleaned = walk(schema) as Record<string, unknown>;
  if (cleaned.type !== "object") cleaned.type = "object";
  if (!cleaned.properties) cleaned.properties = {};
  return cleaned;
}

function toOpenAITools(tools: McpTool[]): OpenAI.Chat.Completions.ChatCompletionTool[] {
  return tools.map((t) => ({
    type: "function",
    function: {
      name: t.name,
      description: t.description.slice(0, 1024),
      parameters: sanitizeSchema(t.inputSchema),
    },
  }));
}

function systemPrompt(cfg: AgentConfig, hasAuth: boolean): string {
  const appetite = {
    conservative: "Strongly prefer staying flat. Only act on clearly one-sided evidence.",
    balanced: "Take a position when evidence leans one way; prefer flat when mixed.",
    aggressive: "Act on moderate edges, but never against crowded, expensive-to-hold setups.",
  }[cfg.riskAppetite];

  const tradingClause = cfg.dryRun
    ? "This is a DRY RUN. Do NOT call any order or leverage tool. Analyze, decide, and state the order you WOULD place (side, size, leverage) — but place nothing."
    : hasAuth
      ? "You may place PAPER orders on the demo account using the write tools. Risk caps are enforced by the harness; if a call is rejected, respect it and size down."
      : "No trading credentials are configured, so you can read market data but cannot place orders. Produce an analysis and the order you would place if able.";

  return [
    "You are a disciplined BTC perpetual-futures trading agent running on Bitget DEMO (paper) trading.",
    "",
    "Work in three phases each cycle:",
    "1. PERCEIVE — call the Bitget read tools to gather: recent candles (trend/volatility), funding rate, open interest, ticker, and your current positions. Do not guess values; fetch them.",
    "2. DECIDE — classify the regime as trending, ranging, or unclear, weigh funding and positioning, and decide: long, short, or flat. Prefer flat when the picture is mixed.",
    "3. ACT — " + tradingClause,
    "",
    `Risk appetite: ${cfg.riskAppetite}. ${appetite}`,
    `Trade only ${cfg.symbol}. Keep size small and leverage modest. Always state a stop level in your reasoning.`,
    "",
    "Call tools one or a few at a time. When done, reply with NO tool calls and a short verdict: regime, decision (long/short/flat), confidence, the key risk, and the exact order (or 'no order').",
  ].join("\n");
}

export async function runCycle(
  bridge: BitgetBridge,
  cfg: AgentConfig,
  onEvent: (e: AgentEvent) => void,
): Promise<{ finalText: string; placedOrders: number }> {
  const apiKey = process.env.OPENROUTER_API_KEY;
  if (!apiKey) throw new Error("OPENROUTER_API_KEY is not set");

  const client = new OpenAI({
    baseURL: "https://openrouter.ai/api/v1",
    apiKey,
    defaultHeaders: {
      "HTTP-Referer": "https://github.com/bitget-hackathon/regime-agent",
      "X-Title": "Adaptive Regime AI Agent",
    },
  });
  const model = process.env.OPENROUTER_MODEL ?? DEFAULT_MODEL;
  const maxIterations = cfg.maxIterations ?? 12;

  // In dry-run, hide write tools entirely so they can't be called.
  const visibleTools = cfg.dryRun
    ? bridge.tools.filter((t) => !/place_order|set_leverage|cancel_orders|update_config|transfer|withdraw/.test(t.name))
    : bridge.tools;
  const tools = toOpenAITools(visibleTools);

  const messages: OpenAI.Chat.Completions.ChatCompletionMessageParam[] = [
    { role: "system", content: systemPrompt(cfg, bridge.hasAuth()) },
    { role: "user", content: `Run one trading cycle for ${cfg.symbol} now. Start by perceiving the market.` },
  ];

  let placedOrders = 0;
  let finalText = "";

  for (let i = 0; i < maxIterations; i++) {
    const resp = await client.chat.completions.create({
      model,
      messages,
      tools,
      tool_choice: "auto",
      max_tokens: 2000,
    });

    const msg = resp.choices[0]?.message;
    if (!msg) break;
    messages.push(msg);

    if (msg.content) {
      onEvent({ kind: "text", text: msg.content });
      finalText = msg.content;
    }

    const toolCalls = msg.tool_calls ?? [];
    if (toolCalls.length === 0) break; // verdict reached

    for (const tc of toolCalls) {
      if (tc.type !== "function") continue;
      let input: Record<string, unknown> = {};
      try {
        input = tc.function.arguments ? JSON.parse(tc.function.arguments) : {};
      } catch {
        /* leave empty; bridge will report a bad call */
      }
      onEvent({ kind: "tool_call", name: tc.function.name, input });
      const res = await bridge.callTool(tc.function.name, input);
      if (tc.function.name.endsWith("place_order") && res.ok) placedOrders++;
      onEvent({ kind: "tool_result", name: tc.function.name, ok: res.ok, text: res.text });
      messages.push({ role: "tool", tool_call_id: tc.id, content: res.text.slice(0, 6000) });
    }
  }

  onEvent({ kind: "done", finalText, placedOrders });
  return { finalText, placedOrders };
}
