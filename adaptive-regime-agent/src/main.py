"""Adaptive Regime AI Agent — entry point.

Live, signal-only LLM agent for BTC perpetual futures. Each scheduled cycle it:

1. Assembles a market briefing from managed data (price regime features from
   klines, plus funding rate, open interest, and crowd positioning when
   available).
2. Asks a bounded language model to reason over that briefing like a
   disciplined futures analyst and return a structured decision.
3. Emits a managed signal (long / short / close / watch) with the model's
   confidence and written rationale.

This is `runtime_profile: llm_bounded` / `backtest_support: none`: open-ended
model reasoning cannot be faithfully replayed, so there is no historical
backtest path. Missing data inputs are reported to the model and surfaced in
the signal meta — never silently faked.
"""
import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np

from getagent import data, llm, runtime

VALID_ACTIONS = {"long", "short", "close", "watch"}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _finite(x: Any, nd: int = 6) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, nd) if math.isfinite(v) else None


def _base_asset(symbol: str) -> str:
    for quote in ("USDT", "USDC", "USD"):
        if symbol.endswith(quote):
            return symbol[: -len(quote)]
    return symbol


def _ema(series: np.ndarray, period: int) -> float:
    alpha = 2.0 / (period + 1)
    ema = float(series[0])
    for v in series[1:]:
        ema = alpha * float(v) + (1.0 - alpha) * ema
    return ema


def _price_features(symbol: str, lookback_hours: int) -> tuple[dict, list[str]]:
    """Backbone features from 1h klines. Raises if klines are unavailable."""
    limit = int(max(120, min(1000, lookback_hours + 60)))
    bars = data.crypto.futures.kline(symbol=symbol, interval="1h", limit=limit)
    df = data.to_dataframe(bars)
    df.columns = [str(c).lower() for c in df.columns]
    if df.empty or "close" not in df.columns:
        raise RuntimeError("no kline rows returned")
    if "date" in df.columns:
        df = df.sort_values("date")

    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float) if "high" in df else close
    low = df["low"].to_numpy(dtype=float) if "low" in df else close
    n = len(close)

    rets = np.diff(close) / close[:-1]
    lb = int(min(lookback_hours, n - 1))
    er_num = abs(close[-1] - close[-1 - lb])
    er_den = float(np.sum(np.abs(np.diff(close[-1 - lb:]))))
    efficiency_ratio = er_num / er_den if er_den > 0 else 0.0

    fast = _ema(close[-60:], 20)
    slow = _ema(close[-120:] if n >= 120 else close, 50)
    tr = np.maximum(high[1:] - low[1:],
                    np.maximum(np.abs(high[1:] - close[:-1]),
                               np.abs(low[1:] - close[:-1])))
    atr = float(np.mean(tr[-14:])) if len(tr) >= 14 else float(np.mean(tr))
    win = close[-lb:]
    z = (close[-1] - float(win.mean())) / float(win.std()) if win.std() > 0 else 0.0

    if efficiency_ratio >= 0.45:
        regime = "trending"
    elif efficiency_ratio <= 0.20:
        regime = "ranging"
    else:
        regime = "unclear"

    feats = {
        "last_price": _finite(close[-1], 2),
        "return_lookback_pct": _finite((close[-1] / close[-1 - lb] - 1.0) * 100.0, 3),
        "trend_alignment": "up" if fast >= slow else "down",
        "fast_vs_slow_ema_gap_pct": _finite((fast - slow) / slow * 100.0, 3),
        "efficiency_ratio": _finite(efficiency_ratio, 3),
        "regime": regime,
        "realized_vol_hourly_pct": _finite(float(np.std(rets[-lb:])) * 100.0, 3),
        "atr_pct_of_price": _finite(atr / close[-1] * 100.0, 3),
        "zscore_vs_lookback_mean": _finite(z, 3),
        "drawdown_from_lookback_high_pct": _finite(
            (close[-1] / float(win.max()) - 1.0) * 100.0, 3),
        "rally_from_lookback_low_pct": _finite(
            (close[-1] / float(win.min()) - 1.0) * 100.0, 3),
        "bars_used": int(n),
    }
    return feats, []


def _optional_context(symbol: str) -> tuple[dict, list[str]]:
    """Best-effort enrichment. Anything that fails is reported as unavailable."""
    ctx: dict[str, Any] = {}
    missing: list[str] = []

    # Funding rate (Coinglass-style funding expects the base asset, e.g. BTC).
    try:
        fr = data.to_dataframe(
            data.crypto.futures.funding_rate(
                symbol=_base_asset(symbol), exchange="bitget", interval="4h", limit=60))
        if not fr.empty and "funding_rate" in fr:
            vals = fr["funding_rate"].to_numpy(dtype=float)
            ctx["funding_rate_latest_pct"] = _finite(vals[-1] * 100.0, 5)
            ctx["funding_rate_avg_recent_pct"] = _finite(float(np.mean(vals[-18:])) * 100.0, 5)
        else:
            missing.append("funding_rate")
    except Exception:
        missing.append("funding_rate")

    # Open interest trend.
    try:
        oi = data.to_dataframe(
            data.crypto.futures.open_interest(
                symbol=symbol, exchange="bitget", interval="1h", limit=72))
        if not oi.empty and "open_interest" in oi:
            vals = oi["open_interest"].to_numpy(dtype=float)
            ctx["open_interest_latest"] = _finite(vals[-1], 2)
            base = vals[-24] if len(vals) >= 24 else vals[0]
            ctx["open_interest_change_24h_pct"] = _finite(
                (vals[-1] / base - 1.0) * 100.0 if base else None, 3)
        else:
            missing.append("open_interest")
    except Exception:
        missing.append("open_interest")

    # Crowd positioning (long/short account ratio).
    try:
        ls = data.to_dataframe(
            data.crypto.futures.long_short_ratio(
                symbol=symbol, exchange="bitget", interval="1h", limit=48))
        if not ls.empty and "long_short_ratio" in ls:
            ctx["long_short_ratio_latest"] = _finite(ls["long_short_ratio"].to_numpy(dtype=float)[-1], 3)
            if "long_account" in ls:
                ctx["long_account_pct"] = _finite(ls["long_account"].to_numpy(dtype=float)[-1], 3)
        else:
            missing.append("long_short_ratio")
    except Exception:
        missing.append("long_short_ratio")

    return ctx, missing


def _build_prompt(symbol: str, risk_appetite: str, brief: dict,
                  missing: list[str]) -> tuple[str, str]:
    appetite_note = {
        "conservative": "Bias toward flat. Only take a position when evidence is clearly one-sided.",
        "balanced": "Take a position when evidence leans one way; prefer flat when mixed.",
        "aggressive": "Act on moderate edges, but never trade against clearly crowded, expensive-to-hold setups.",
    }.get(risk_appetite, "Take a position when evidence leans one way; prefer flat when mixed.")

    system = (
        "You are a disciplined crypto perpetual-futures analyst. You weigh "
        "conflicting evidence honestly, you are comfortable choosing to stay "
        "flat, and you never claim certainty you do not have. You output strict "
        "JSON only."
    )
    missing_line = (
        f"Unavailable inputs this cycle (do not assume values): {', '.join(missing)}."
        if missing else "All standard inputs are available this cycle."
    )
    user = (
        f"Market briefing for {symbol} (perpetual futures).\n"
        f"{missing_line}\n"
        f"Risk appetite: {risk_appetite}. {appetite_note}\n\n"
        f"DATA:\n{json.dumps(brief, indent=2)}\n\n"
        "Decide the position to hold for roughly the next several hours. "
        "Respond with strict JSON and nothing else, using exactly these keys:\n"
        '{"action": "long|short|flat|close", '
        '"thesis": "bull|bear|neutral", '
        '"confidence": <number 0..1>, '
        '"rationale": "<=240 chars on the main drivers", '
        '"key_risks": "<=160 chars on what would invalidate this"}'
    )
    return system, user


def _parse_decision(content: str) -> dict:
    text = content.strip()
    try:
        obj = json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            raise ValueError("model did not return JSON")
        obj = json.loads(m.group(0))

    raw_action = str(obj.get("action", "")).strip().lower()
    action = {"flat": "watch", "none": "watch", "neutral": "watch",
              "hold": "watch"}.get(raw_action, raw_action)
    if action not in VALID_ACTIONS:
        action = "watch"
    conf = _finite(obj.get("confidence"), 4)
    if conf is None:
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    return {
        "action": action,
        "thesis": str(obj.get("thesis", "")).strip().lower()[:16],
        "confidence": conf,
        "rationale": str(obj.get("rationale", ""))[:240],
        "key_risks": str(obj.get("key_risks", ""))[:160],
    }


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def run() -> None:
    cfg = runtime.manifest.get("strategy_config", {}) or {}
    symbol = (cfg.get("trading_symbols") or ["BTCUSDT"])[0]
    risk_appetite = str(cfg.get("risk_appetite", "balanced"))
    lookback_hours = int(cfg.get("lookback_hours", 168) or 168)
    temperature = float(cfg.get("model_temperature", 0.2) or 0.2)

    # Backbone price features are required; without them there is no decision.
    try:
        brief, _ = _price_features(symbol, lookback_hours)
    except Exception as exc:
        runtime.emit_signal(
            action="watch", symbol=symbol, confidence=0.0,
            metrics={"data_ok": 0},
            meta={"reason": f"market data unavailable: {exc}"})
        return

    ctx, missing = _optional_context(symbol)
    brief.update(ctx)

    if not llm.is_available():
        # The model is the decision engine; without it we stand aside honestly.
        runtime.emit_signal(
            action="watch", symbol=symbol, confidence=0.0,
            metrics=_signal_metrics(brief),
            meta={"reason": "bounded LLM runtime not available this run",
                  "regime": brief.get("regime"), "missing_inputs": missing})
        return

    system, user = _build_prompt(symbol, risk_appetite, brief, missing)
    try:
        result = llm.complete(user, system=system, max_tokens=500, temperature=temperature)
        decision = _parse_decision(result.content)
        model_name = getattr(result, "model", None)
    except Exception as exc:
        runtime.emit_signal(
            action="watch", symbol=symbol, confidence=0.0,
            metrics=_signal_metrics(brief),
            meta={"reason": f"agent reasoning failed: {exc}",
                  "regime": brief.get("regime"), "missing_inputs": missing})
        return

    runtime.emit_signal(
        action=decision["action"],
        symbol=symbol,
        confidence=decision["confidence"],
        metrics=_signal_metrics(brief),
        meta={
            "thesis": decision["thesis"],
            "rationale": decision["rationale"],
            "key_risks": decision["key_risks"],
            "risk_appetite": risk_appetite,
            "regime": brief.get("regime"),
            "missing_inputs": missing,
            "llm_model": model_name,
            "decided_at": datetime.now(tz=timezone.utc).isoformat(),
        },
    )


def _signal_metrics(brief: dict) -> dict:
    keys = ["last_price", "return_lookback_pct", "efficiency_ratio",
            "zscore_vs_lookback_mean", "realized_vol_hourly_pct",
            "funding_rate_latest_pct", "open_interest_change_24h_pct",
            "long_short_ratio_latest"]
    return {k: brief[k] for k in keys if k in brief and brief[k] is not None}


if __name__ == "__main__":
    run()
