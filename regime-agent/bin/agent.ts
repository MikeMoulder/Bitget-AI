/**
 * Run one perceive→decide→act cycle of the Adaptive Regime agent and print the
 * trace to the terminal.
 *
 *   npm run agent              # dry run (analyze only, no orders)
 *   npm run agent -- --live    # place paper orders on the demo account
 *
 * Requires ANTHROPIC_API_KEY. Placing paper orders also requires Bitget DEMO
 * BITGET_API_KEY / BITGET_SECRET_KEY / BITGET_PASSPHRASE.
 */
import { BitgetBridge } from "../lib/bitget-mcp.js";
import { runCycle, type AgentEvent, type AgentConfig } from "../lib/agent.js";
import { bitgetCreds, DEFAULT_RISK_CAPS } from "../lib/config.js";

function render(e: AgentEvent) {
  switch (e.kind) {
    case "text":
      console.log(`\n💬 ${e.text.trim()}`);
      break;
    case "tool_call":
      console.log(`\n🔧 → ${e.name}(${JSON.stringify(e.input)})`);
      break;
    case "tool_result":
      console.log(`   ${e.ok ? "✅" : "⛔"} ${e.text.slice(0, 240).replace(/\s+/g, " ")}`);
      break;
    case "done":
      console.log(`\n──────── cycle complete · paper orders placed: ${e.placedOrders} ────────`);
      break;
  }
}

async function main() {
  const live = process.argv.includes("--live");
  const cfg: AgentConfig = {
    symbol: process.env.AGENT_SYMBOL ?? "BTCUSDT",
    riskAppetite: (process.env.AGENT_RISK_APPETITE as AgentConfig["riskAppetite"]) ?? "balanced",
    dryRun: !live,
  };

  console.log(
    `Adaptive Regime Agent · ${cfg.symbol} · ${cfg.riskAppetite} · ${live ? "LIVE PAPER" : "DRY RUN"}`,
  );

  // Note: --paper-trading and --read-only are mutually exclusive in the Bitget
  // MCP server. Dry-run safety comes from agent-side write-tool filtering
  // (lib/agent.ts) plus the bridge risk caps, so we keep paper mode on.
  const bridge = await BitgetBridge.connect({
    ...bitgetCreds(),
    modules: "futures,account",
    paperTrading: true,
    riskCaps: DEFAULT_RISK_CAPS,
  });

  if (live && !bridge.hasAuth()) {
    console.error("⛔ --live needs BITGET_API_KEY / BITGET_SECRET_KEY / BITGET_PASSPHRASE (demo keys).");
    await bridge.close();
    process.exit(1);
  }

  try {
    await runCycle(bridge, cfg, render);
  } finally {
    await bridge.close();
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
