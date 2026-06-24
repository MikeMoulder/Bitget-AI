import "dotenv/config";
import type { RiskCaps } from "./bitget-mcp.js";

export function bitgetCreds() {
  return {
    apiKey: process.env.BITGET_API_KEY,
    secretKey: process.env.BITGET_SECRET_KEY,
    passphrase: process.env.BITGET_PASSPHRASE,
  };
}

export const DEFAULT_RISK_CAPS: RiskCaps = {
  allowedSymbols: (process.env.AGENT_ALLOWED_SYMBOLS ?? "BTCUSDT").split(","),
  maxOrderSize: Number(process.env.AGENT_MAX_ORDER_SIZE ?? "0.01"),
  maxLeverage: Number(process.env.AGENT_MAX_LEVERAGE ?? "3"),
};
