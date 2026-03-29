"""
使用 AKShare 拉取 A 股 / ETF 日线，并映射为 Agent 所需的 price 快照字段。
网络或接口变更时由 registry 回退到 mock。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from ..memory.symbol_meta_cache import SymbolMetaCache


def _normalize_code(raw: str) -> str:
    s = "".join(c for c in (raw or "").strip().upper() if c.isalnum())
    if s.isdigit():
        return s.zfill(6)[-6:]
    return s


def _pick_col(df: pd.DataFrame, *names: str) -> str | None:
    for n in names:
        if n in df.columns:
            return n
    return None


def _prefer_etf_daily_api(code: str) -> bool:
    """按常见代码段判断：先走 ETF 日线接口。"""
    if len(code) != 6 or not code.isdigit():
        return False
    if code.startswith(("51", "56", "58")):
        return True
    if code.startswith(("15", "16")):
        return True
    return False


def _fetch_etf_daily(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    import akshare as ak

    # 东财 ETF 日线；不同版本参数名一致
    df = ak.fund_etf_hist_em(
        symbol=code,
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust="",
    )
    return df if isinstance(df, pd.DataFrame) else pd.DataFrame()


def _fetch_stock_daily(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    import akshare as ak

    df = ak.stock_zh_a_hist(
        symbol=code,
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust="",
    )
    return df if isinstance(df, pd.DataFrame) else pd.DataFrame()


# 仅需最近 K 线算涨跌与收盘；过长的回溯会显著增大东财返回体积与耗时
_DEFAULT_LOOKBACK_DAYS = 120


def fetch_daily_bars(
    code: str, lookback_calendar_days: int = _DEFAULT_LOOKBACK_DAYS
) -> tuple[pd.DataFrame, str]:
    """
    返回 (按日期升序的 DataFrame, 数据源标记 etf|stock)。
    """
    code = _normalize_code(code)
    if len(code) != 6 or not code.isdigit():
        raise ValueError(f"invalid_code:{code}")

    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=lookback_calendar_days)).strftime("%Y%m%d")

    errors: list[str] = []

    def try_both() -> tuple[pd.DataFrame, str]:
        if _prefer_etf_daily_api(code):
            try:
                df = _fetch_etf_daily(code, start, end)
                if not df.empty:
                    return df, "etf"
            except Exception as e:  # noqa: BLE001
                errors.append(f"etf:{e!s}")
            try:
                df = _fetch_stock_daily(code, start, end)
                if not df.empty:
                    return df, "stock"
            except Exception as e:  # noqa: BLE001
                errors.append(f"stock:{e!s}")
        else:
            try:
                df = _fetch_stock_daily(code, start, end)
                if not df.empty:
                    return df, "stock"
            except Exception as e:  # noqa: BLE001
                errors.append(f"stock:{e!s}")
            try:
                df = _fetch_etf_daily(code, start, end)
                if not df.empty:
                    return df, "etf"
            except Exception as e:  # noqa: BLE001
                errors.append(f"etf:{e!s}")
        raise RuntimeError("akshare_daily_empty:" + ";".join(errors) if errors else "unknown")

    return try_both()


def _parse_pct_cell(val: Any) -> float | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace("%", "")
    try:
        return float(s)
    except ValueError:
        return None


def _latest_metrics(df: pd.DataFrame) -> dict[str, Any]:
    if df is None or df.empty:
        raise ValueError("empty_dataframe")

    date_col = _pick_col(df, "日期", "date", "Date")
    close_col = _pick_col(df, "收盘", "close", "Close")
    pct_col = _pick_col(df, "涨跌幅", "涨跌幅(%)", "pct_chg")

    if date_col is None or close_col is None:
        raise ValueError(f"unknown_columns:{list(df.columns)}")

    sorted_df = df.copy()
    sorted_df[date_col] = pd.to_datetime(sorted_df[date_col], errors="coerce")
    sorted_df = sorted_df.dropna(subset=[date_col]).sort_values(date_col)
    if sorted_df.empty:
        raise ValueError("no_valid_dates")

    last = sorted_df.iloc[-1]
    prev = sorted_df.iloc[-2] if len(sorted_df) > 1 else None

    close = float(last[close_col])
    trade_date = last[date_col].strftime("%Y-%m-%d")

    change_pct: float
    parsed_pct = _parse_pct_cell(last[pct_col]) if pct_col is not None else None
    if parsed_pct is not None:
        change_pct = parsed_pct
    elif prev is not None:
        pclose = float(prev[close_col])
        change_pct = round((close - pclose) / pclose * 100, 4) if pclose else 0.0
    else:
        change_pct = 0.0

    prev_close = float(prev[close_col]) if prev is not None else None

    return {
        "close": round(close, 4),
        "change_pct": round(change_pct, 4),
        "trade_date": trade_date,
        "prev_close": round(prev_close, 4) if prev_close is not None else None,
    }


def get_daily_price_snapshot(
    etf_code: str,
    *,
    include_profile: bool = True,
    lookback_calendar_days: int | None = None,
    symbol_meta_cache: SymbolMetaCache | None = None,
    force_refresh_symbol_meta: bool = False,
) -> dict[str, Any]:
    """
    与 mock `get_etf_price` 对齐的字段，供 RuleEngine 使用。
    可选合并东财名称、类型、行业/板块（见 akshare_meta）。
    lookback_calendar_days 默认使用模块内常量（与 Settings 默认值一致，由 registry 传入配置值）。
    """
    code = _normalize_code(etf_code)
    lb = (
        lookback_calendar_days
        if lookback_calendar_days is not None
        else _DEFAULT_LOOKBACK_DAYS
    )
    lb = max(5, min(int(lb), 3650))
    df, kind = fetch_daily_bars(code, lookback_calendar_days=lb)
    m = _latest_metrics(df)
    base: dict[str, Any] = {
        "etf_code": code,
        "last": m["close"],
        "change_pct": m["change_pct"],
        "currency": "CNY",
        "source": "akshare",
        "period": "daily",
        "trade_date": m["trade_date"],
        "prev_close": m["prev_close"],
        "daily_kind": kind,
    }
    if include_profile:
        try:
            from .akshare_meta import fetch_security_profile, merge_profile_into_price_dict

            prof = fetch_security_profile(
                code,
                cache=symbol_meta_cache,
                force_refresh=force_refresh_symbol_meta,
            )
            base = merge_profile_into_price_dict(base, prof)
        except Exception:  # noqa: BLE001
            pass
    return base
