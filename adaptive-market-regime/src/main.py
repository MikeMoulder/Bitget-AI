"""Entry point for the Adaptive Market Regime Playbook.

For backtest_support: full playbooks the platform injects
runtime.evaluation_mode="historical" on /api/v1/playbook/run. This package is
signal_only, so we only handle the historical/backtest path here and emit a
managed summary signal with the run metrics.
"""
import math
from datetime import datetime, timezone
from typing import Any

from getagent import backtest, data, runtime


def _sanitize(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _sanitize_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {key: _sanitize(val) for key, val in metrics.items()}


def _load_bars(symbol: str, interval: str = "1h", days: int = 180, chunk_days: int = 80):
    """Assemble a multi-month replay frame by paging the kline endpoint.

    The kline endpoint caps each request, so we walk the window in chunks and
    concatenate. Any failure falls back to the proven single-fetch call so the
    run still produces real evidence.
    """
    import pandas as pd

    try:
        now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        span_ms = chunk_days * 24 * 3600 * 1000
        cursor = now_ms - days * 24 * 3600 * 1000
        frames = []
        while cursor < now_ms:
            end = min(cursor + span_ms, now_ms)
            chunk = data.crypto.futures.kline(
                symbol=symbol,
                interval=interval,
                start_time=cursor,
                end_time=end,
                limit=1000,
            )
            frame = backtest.prepare_frame(chunk, datetime_index="date")
            if not frame.empty:
                frames.append(frame)
            cursor = end
        if frames:
            combined = pd.concat(frames).sort_index()
            combined = combined[~combined.index.duplicated(keep="last")]
            if len(combined) >= 100:
                return combined
    except Exception:
        pass

    # Fallback: most recent 1000 bars in a single request.
    bars = data.crypto.futures.kline(symbol=symbol, interval=interval, limit=1000)
    return backtest.prepare_frame(bars, datetime_index="date")


def run() -> None:
    cfg = runtime.manifest.get("strategy_config", {}) or {}
    symbols = cfg.get("trading_symbols") or ["BTCUSDT"]
    symbol = symbols[0]

    replay_frame = _load_bars(symbol, interval="1h", days=360)

    if replay_frame.empty:
        runtime.emit_signal(
            action="watch",
            symbol=symbol,
            confidence=0.0,
            metrics={"rows": 0},
            meta={"reason": "no historical bars returned"},
        )
        return

    instrument_key = f"{symbol}.BINANCE"
    result = backtest.run(
        ohlcv_data={instrument_key: replay_frame},
        spec=runtime.backtest_spec,
    )

    chart_path = backtest.generate_chart(result)
    summary = result.summary or {}
    try:
        net_pnl = float(summary.get("net_pnl", 0) or 0)
    except (TypeError, ValueError):
        net_pnl = 0.0

    action = "long" if net_pnl > 0 else "watch"
    metrics = _sanitize_metrics(
        {
            "total_return_pct": result.total_return_pct,
            "net_pnl": net_pnl,
            "starting_balance": summary.get("starting_balance"),
            "sharpe_ratio": result.sharpe_ratio,
            "max_drawdown_pct": result.max_drawdown_pct,
            "win_rate": result.win_rate,
            "total_trades": result.total_trades,
            "profit_factor": result.profit_factor,
            "rows": len(replay_frame),
        }
    )

    runtime.emit_signal(
        action=action,
        symbol=symbol,
        confidence=_sanitize(result.win_rate) or 0.0,
        metrics=metrics,
        meta={
            "chart_path": chart_path,
            "regime_engine": "efficiency-ratio + ma-alignment + zscore",
            "trend_fast": cfg.get("trend_fast"),
            "trend_slow": cfg.get("trend_slow"),
        },
    )


if __name__ == "__main__":
    run()
