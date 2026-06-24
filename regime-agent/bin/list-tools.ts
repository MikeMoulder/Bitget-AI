/**
 * Smoke test: start the Bitget MCP server (paper mode) and list its tools.
 * Requires NO credentials — verifies the stdio bridge works end to end.
 *
 *   npm run tools
 */
import { BitgetBridge } from "../lib/bitget-mcp.js";
import { bitgetCreds, DEFAULT_RISK_CAPS } from "../lib/config.js";

async function main() {
  const bridge = await BitgetBridge.connect({
    ...bitgetCreds(),
    modules: "futures,account",
    paperTrading: true,
    riskCaps: DEFAULT_RISK_CAPS,
  });

  console.log(`Connected. auth=${bridge.hasAuth()} | ${bridge.tools.length} tools:\n`);
  for (const t of bridge.tools) {
    const desc = (t.description ?? "").split("\n")[0].slice(0, 70);
    console.log(`  ${t.name.padEnd(34)} ${desc}`);
  }

  // Call a read-only capability probe (no auth required).
  const caps = await bridge.callTool("system_get_capabilities", {});
  console.log(`\nsystem_get_capabilities ok=${caps.ok}`);
  console.log(caps.text.slice(0, 400));

  await bridge.close();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
