"""
从 AKShare 拉取证券名称、类型、行业/板块等。

性能说明：历史上使用 stock_zh_a_spot_em（全市场 A 股）会导致单次请求接近 1 分钟。
股票侧已改为仅调用 stock_individual_info_em（单标的）；ETF 仍用 fund_etf_spot_em 全表但带较长缓存。
"""

from __future__ import annotations

import time
from typing import Any

import pandas as pd

from ..memory.symbol_meta_cache import SymbolMetaCache
from .akshare_daily import _normalize_code, _pick_col, _prefer_etf_daily_api


def _should_persist_profile(p: dict[str, Any]) -> bool:
    if str(p.get("name") or "").strip():
        return True
    at = str(p.get("asset_type") or "unknown")
    return at not in ("", "unknown")

# ETF 全表体积小于 A 股全市场；缓存久一点避免连续分析重复拉取
_SPOT_ETF_TTL_SEC = 900.0
_etf_spot_cache: tuple[float, pd.DataFrame] | None = None


def _etf_spot_df() -> pd.DataFrame:
    global _etf_spot_cache
    import akshare as ak

    now = time.monotonic()
    if _etf_spot_cache is not None and now - _etf_spot_cache[0] < _SPOT_ETF_TTL_SEC:
        return _etf_spot_cache[1]
    df = ak.fund_etf_spot_em()
    df = df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    _etf_spot_cache = (now, df)
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


def _stock_meta_from_info_em(code: str) -> dict[str, Any] | None:
    """
    单请求拉取股票简称/行业等；避免 stock_zh_a_spot_em 全市场接口。
    若不像有效 A 股资料则返回 None。
    """
    import akshare as ak

    try:
        info = ak.stock_individual_info_em(symbol=code)
        kv = _info_em_to_dict(info if isinstance(info, pd.DataFrame) else pd.DataFrame())
    except Exception:  # noqa: BLE001
        return None
    if not kv:
        return None
    name = (
        kv.get("股票简称")
        or kv.get("股票名称")
        or kv.get("证券简称")
        or kv.get("名称")
        or ""
    )
    industry = kv.get("行业", "") or kv.get("所属行业", "") or kv.get("证监会行业", "")
    if not name.strip() and not industry.strip():
        return None
    conc = kv.get("概念板块") or kv.get("涉及概念") or kv.get("相关概念") or ""
    return {
        "name": name.strip(),
        "asset_type": "stock",
        "industry": industry,
        "sector": kv.get("所属板块", "") or kv.get("板块", ""),
        "listing_board": kv.get("上市板块", "")
        or kv.get("市场类型", "")
        or kv.get("板块", ""),
        "concept": conc[:400] if conc else "",
        "source": "akshare",
    }


def fetch_security_profile(
    code: str,
    *,
    cache: SymbolMetaCache | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """
    返回名称、资产类型、行业、板块、概念摘要等。
    若提供 cache 且非 force_refresh，命中磁盘缓存则不再请求网络。
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

    if cache is not None and not force_refresh:
        hit = cache.get(code)
        if hit is not None:
            return {
                "code": hit.get("code") or code,
                "name": str(hit.get("name") or ""),
                "asset_type": str(hit.get("asset_type") or "unknown"),
                "industry": str(hit.get("industry") or ""),
                "sector": str(hit.get("sector") or ""),
                "concept": str(hit.get("concept") or ""),
                "listing_board": str(hit.get("listing_board") or ""),
                "fund_type_detail": str(hit.get("fund_type_detail") or ""),
                "source": str(hit.get("source") or "disk_cache"),
                "meta_source": "disk_cache",
            }

    tried_etf = _prefer_etf_daily_api(code)
    if tried_etf:
        row = _row_match_code(_etf_spot_df(), code, "基金代码", "代码")
        if row is not None:
            out["name"] = _series_get(row, "基金简称", "名称", "基金名称")
            out["asset_type"] = "etf"
            ft = _series_get(row, "基金类型", "类型", "跟踪指数")
            if ft:
                out["fund_type_detail"] = ft
            if cache is not None and _should_persist_profile(out):
                cache.set_from_profile(code, out)
            return out

    # 股票：禁止再走全市场 spot，只用个股资料接口
    sm = _stock_meta_from_info_em(code)
    if sm is not None:
        out.update(sm)
        if cache is not None and _should_persist_profile(out):
            cache.set_from_profile(code, out)
        return out

    if not tried_etf:
        row = _row_match_code(_etf_spot_df(), code, "基金代码", "代码")
        if row is not None:
            out["name"] = _series_get(row, "基金简称", "名称", "基金名称")
            out["asset_type"] = "etf"
            ft = _series_get(row, "基金类型", "类型")
            if ft:
                out["fund_type_detail"] = ft
            if cache is not None and _should_persist_profile(out):
                cache.set_from_profile(code, out)
            return out

    if cache is not None and _should_persist_profile(out):
        cache.set_from_profile(code, out)
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
