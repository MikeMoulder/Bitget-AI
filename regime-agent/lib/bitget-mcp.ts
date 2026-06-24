/**
 * Bridge to the official Bitget MCP server (stdio).
 *
 * The MCP *connector* on the Messages API is HTTP/URL-only and runs server-side,
 * so it cannot talk to `bitget-mcp-server`, which is a local stdio process. We
 * therefore bridge it client-side: spawn the server, list its tools, expose them
 * to Claude as tool definitions, and forward Claude's tool calls to the server.
 *
 * The bridge also enforces paper-mode RISK CAPS on write tools (e.g. order size,
 * allowed symbols) so the agent physically cannot exceed configured limits, no
 * matter what the model decides.
 */
import { createRequire } from "node:module";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const require = createRequire(import.meta.url);

/** Provider-neutral tool descriptor (converted to OpenAI/Anthropic shape by the brain). */
export interface McpTool {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
}

export interface RiskCaps {
  /** Only these exchange-native symbols may be traded. */
  allowedSymbols: string[];
  /** Max contracts per single order (rejected above this). */
  maxOrderSize: number;
  /** Max leverage the agent may set. */
  maxLeverage: number;
}

export interface BridgeOptions {
  /** Bitget DEMO API credentials (paper trading). */
  apiKey?: string;
  secretKey?: string;
  passphrase?: string;
  /** MCP modules to load. Default: futures,account. */
  modules?: string;
  /** Paper/demo trading (adds the paptrading:1 header). Default true. */
  paperTrading?: boolean;
  /** Expose only read tools (disable all writes). Default false. */
  readOnly?: boolean;
  riskCaps: RiskCaps;
}

export interface ToolCallResult {
  ok: boolean;
  text: string;
}

export class BitgetBridge {
  private client: Client;
  private transport: StdioClientTransport;
  private opts: BridgeOptions;
  tools: McpTool[] = [];

  private constructor(client: Client, transport: StdioClientTransport, opts: BridgeOptions) {
    this.client = client;
    this.transport = transport;
    this.opts = opts;
  }

  static async connect(opts: BridgeOptions): Promise<BitgetBridge> {
    const serverEntry = require.resolve("bitget-mcp-server/dist/index.js");
    const args = [serverEntry, "--modules", opts.modules ?? "futures,account"];
    if (opts.paperTrading ?? true) args.push("--paper-trading");
    if (opts.readOnly) args.push("--read-only");

    const transport = new StdioClientTransport({
      command: process.execPath, // node
      args,
      env: {
        ...(process.env as Record<string, string>),
        ...(opts.apiKey ? { BITGET_API_KEY: opts.apiKey } : {}),
        ...(opts.secretKey ? { BITGET_SECRET_KEY: opts.secretKey } : {}),
        ...(opts.passphrase ? { BITGET_PASSPHRASE: opts.passphrase } : {}),
      },
      stderr: "pipe",
    });

    const client = new Client(
      { name: "regime-agent", version: "0.1.0" },
      { capabilities: {} },
    );
    await client.connect(transport);

    const bridge = new BitgetBridge(client, transport, opts);
    await bridge.loadTools();
    return bridge;
  }

  private async loadTools(): Promise<void> {
    const { tools } = await this.client.listTools();
    this.tools = tools.map((t) => ({
      name: t.name,
      description: t.description ?? "",
      inputSchema: (t.inputSchema ?? { type: "object" }) as Record<string, unknown>,
    }));
  }

  /** Forward a Claude tool call to the MCP server, after enforcing risk caps. */
  async callTool(name: string, input: Record<string, unknown>): Promise<ToolCallResult> {
    const guard = this.enforceRiskCaps(name, input);
    if (guard) return { ok: false, text: `RISK CAP REJECTED: ${guard}` };

    try {
      const res = (await this.client.callTool({ name, arguments: input })) as {
        isError?: boolean;
        content?: Array<{ type: string; text?: string }>;
      };
      const text = (res.content ?? [])
        .map((c) => (c.type === "text" ? c.text ?? "" : `[${c.type}]`))
        .join("\n");
      return { ok: !res.isError, text: text || "(empty result)" };
    } catch (err) {
      return { ok: false, text: `MCP error: ${(err as Error).message}` };
    }
  }

  /** Returns a rejection reason string if the call violates a risk cap, else null. */
  private enforceRiskCaps(name: string, input: Record<string, unknown>): string | null {
    const { allowedSymbols, maxOrderSize, maxLeverage } = this.opts.riskCaps;
    const symbol = String(input.symbol ?? "");

    if (name.endsWith("place_order")) {
      if (symbol && !allowedSymbols.includes(symbol)) {
        return `symbol ${symbol} not in allowlist [${allowedSymbols.join(", ")}]`;
      }
      const size = Number(input.size ?? input.qty ?? input.quantity ?? 0);
      if (!Number.isFinite(size) || size <= 0) return `invalid order size: ${input.size}`;
      if (size > maxOrderSize) return `order size ${size} exceeds cap ${maxOrderSize}`;
    }
    if (name.endsWith("set_leverage")) {
      const lev = Number(input.leverage ?? 0);
      if (lev > maxLeverage) return `leverage ${lev} exceeds cap ${maxLeverage}`;
    }
    return null;
  }

  hasAuth(): boolean {
    return Boolean(this.opts.apiKey && this.opts.secretKey && this.opts.passphrase);
  }

  async close(): Promise<void> {
    await this.client.close();
    await this.transport.close();
  }
}
