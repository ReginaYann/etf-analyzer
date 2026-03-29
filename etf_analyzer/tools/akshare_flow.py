"""
东财个股/ETF 资金流向（日线级），映射为与 mock 一致的 main_force_net_wan / retail_net_wan（万元）。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .akshare_daily import _normalize_code, _pick_col


def _to_float(val: Any) -> float | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _find_amount_col(df: pd.DataFrame, *keywords: str) -> str | None:
    for c in df.columns:
        cs = str(c)
        if all(k in cs for k in keywords):
            return c
    return None


def get_fund_flow_snapshot(etf_code: str) -> dict[str, Any]:
    """
    取 stock_individual_fund_flow 最新一行；金额列一般为「元」，输出转为「万元」。
    """
    code = _normalize_code(etf_code)
    if len(code) != 6 or not code.isdigit():
        raise ValueError(f"invalid_code:{code}")

    import akshare as ak

    df = ak.stock_individual_fund_flow(stock=code)
    if not isinstance(df, pd.DataFrame) or df.empty:
        raise ValueError("empty_fund_flow")

    date_col = _pick_col(df, "日期", "date", "Date")
    if date_col:
        work = df.copy()
        work[date_col] = pd.to_datetime(work[date_col], errors="coerce")
        work = work.dropna(subset=[date_col]).sort_values(date_col)
    else:
        work = df

    if work.empty:
        raise ValueError("no_fund_flow_rows")

    last = work.iloc[-1]

    # 主力净流入-净额（元）；列名随 akshare 版本略有差异
    main_col = (
        _pick_col(work, "主力净流入-净额")
        or _find_amount_col(work, "主力", "净额")
        or _find_amount_col(work, "主力净流入", "净额")
    )
    main_yuan = _to_float(last[main_col]) if main_col else None

    # 中单+小单 近似「散户侧」净额（元）
    mid_col = _find_amount_col(work, "中单", "净额") or _pick_col(work, "中单净流入-净额")
    small_col = _find_amount_col(work, "小单", "净额") or _pick_col(work, "小单净流入-净额")
    mid_yuan = _to_float(last[mid_col]) if mid_col else 0.0
    small_yuan = _to_float(last[small_col]) if small_col else 0.0
    retail_yuan = (mid_yuan or 0.0) + (small_yuan or 0.0)

    if main_yuan is None:
        raise ValueError("no_main_force_column")

    flow_date = None
    if date_col:
        try:
            flow_date = last[date_col].strftime("%Y-%m-%d")
        except Exception:  # noqa: BLE001
            flow_date = str(last[date_col])

    # 超大单、大单（万元）供展示
    xl_col = _find_amount_col(work, "超大单", "净额") or _pick_col(work, "超大单净流入-净额")
    lg_col = _find_amount_col(work, "大单", "净额") or _pick_col(work, "大单净流入-净额")
    xl_wan = round((_to_float(last[xl_col]) or 0.0) / 10000.0, 2) if xl_col else None
    lg_wan = round((_to_float(last[lg_col]) or 0.0) / 10000.0, 2) if lg_col else None

    return {
        "etf_code": code,
        "main_force_net_wan": round(main_yuan / 10000.0, 2),
        "retail_net_wan": round(retail_yuan / 10000.0, 2),
        "flow_date": flow_date,
        "super_large_net_wan": xl_wan,
        "large_net_wan": lg_wan,
        "source": "akshare",
    }
