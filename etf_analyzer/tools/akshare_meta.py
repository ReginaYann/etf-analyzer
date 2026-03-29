"""
从 AKShare 拉取证券名称、类型、行业/板块等（东财全市场 spot + 个股资料）。
"""

from __future__ import annotations

import time
from typing import Any

import pandas as pd

from .akshare_daily import _normalize_code, _pick_col, _prefer_etf_daily_api

_SPOT_TTL_SEC = 90.0
_etf_spot_cache: tuple[float, pd.DataFrame] | None = None
_stock_spot_cache: tuple[float, pd.DataFrame] | None = None


def _etf_spot_df() -> pd.DataFrame:
    global _etf_spot_cache
    import akshare as ak

    now = time.monotonic()
    if _etf_spot_cache is not None and now - _etf_spot_cache[0] < _SPOT_TTL_SEC:
        return _etf_spot_cache[1]
    df = ak.fund_etf_spot_em()
    df = df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    _etf_spot_cache = (now, df)
    return df


def _stock_spot_df() -> pd.DataFrame:
    global _stock_spot_cache
    import akshare as ak

    now = time.monotonic()
    if _stock_spot_cache is not None and now - _stock_spot_cache[0] < _SPOT_TTL_SEC:
        return _stock_spot_cache[1]
    df = ak.stock_zh_a_spot_em()
    df = df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    _stock_spot_cache = (now, df)
    return df


def _row_match_code(df: pd.DataFrame, code: str, *code_col_names: str) -> pd.Series | None:
    if df.empty:
        return None
    col = _pick_col(df, *code_col_names)
    if col is None:
        return None
    s = df[col].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    m = s == code
    if not m.any():
        return None
    return df.loc[m].iloc[0]


def _series_get(row: pd.Series, *candidates: str) -> str:
    for c in candidates:
        if c in row.index and pd.notna(row[c]):
            return str(row[c]).strip()
    return ""


def _info_em_to_dict(df: pd.DataFrame) -> dict[str, str]:
    """东财个股资料：列名可能是 item/value 或 字段/值。"""
    if df is None or df.empty or len(df.columns) < 2:
        return {}
    c0, c1 = df.columns[0], df.columns[1]
    out: dict[str, str] = {}
    for _, row in df.iterrows():
        k = str(row[c0]).strip()
        v = row[c1]
        if k and pd.notna(v):
            out[k] = str(v).strip()
    return out


def fetch_security_profile(code: str) -> dict[str, Any]:
    """
    返回名称、资产类型、行业、板块、概念摘要等；尽量与东财字段对齐。
    """
    code = _normalize_code(code)
    out: dict[str, Any] = {
        "code": code,
        "name": "",
        "asset_type": "unknown",
        "industry": "",
        "sector": "",
        "concept": "",
        "listing_board": "",
        "source": "akshare",
    }
    if len(code) != 6 or not code.isdigit():
        return out

    import akshare as ak

    tried_etf = _prefer_etf_daily_api(code)
    if tried_etf:
        row = _row_match_code(_etf_spot_df(), code, "基金代码", "代码")
        if row is not None:
            out["name"] = _series_get(row, "基金简称", "名称", "基金名称")
            out["asset_type"] = "etf"
            ft = _series_get(row, "基金类型", "类型", "跟踪指数")
            if ft:
                out["fund_type_detail"] = ft
            return out

    row = _row_match_code(_stock_spot_df(), code, "代码")
    if row is not None:
        out["name"] = _series_get(row, "名称")
        out["asset_type"] = "stock"

    if out["asset_type"] == "unknown" and not tried_etf:
        row = _row_match_code(_etf_spot_df(), code, "基金代码", "代码")
        if row is not None:
            out["name"] = _series_get(row, "基金简称", "名称", "基金名称")
            out["asset_type"] = "etf"
            ft = _series_get(row, "基金类型", "类型")
            if ft:
                out["fund_type_detail"] = ft
            return out

    if out["asset_type"] == "stock":
        try:
            info = ak.stock_individual_info_em(symbol=code)
            kv = _info_em_to_dict(info if isinstance(info, pd.DataFrame) else pd.DataFrame())
            out["industry"] = kv.get("行业", "") or kv.get("所属行业", "") or kv.get("证监会行业", "")
            out["sector"] = kv.get("所属板块", "") or kv.get("板块", "")
            out["listing_board"] = kv.get("上市板块", "") or kv.get("市场类型", "") or kv.get("板块", "")
            conc = kv.get("概念板块") or kv.get("涉及概念") or kv.get("相关概念") or ""
            out["concept"] = conc[:400] if conc else ""
        except Exception:  # noqa: BLE001
            pass

    return out


def merge_profile_into_price_dict(price: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """把档案字段摊平到 price 快照，便于 Agent / LLM 单对象传递。"""
    merged = dict(price)
    merged["security_name"] = profile.get("name") or merged.get("security_name", "")
    merged["asset_type"] = profile.get("asset_type") or merged.get("asset_type", "unknown")
    if profile.get("industry"):
        merged["industry"] = profile["industry"]
    if profile.get("sector"):
        merged["sector"] = profile["sector"]
    if profile.get("concept"):
        merged["concept_board"] = profile["concept"]
    if profile.get("listing_board"):
        merged["listing_board"] = profile["listing_board"]
    if profile.get("fund_type_detail"):
        merged["fund_type_detail"] = profile["fund_type_detail"]
    return merged
