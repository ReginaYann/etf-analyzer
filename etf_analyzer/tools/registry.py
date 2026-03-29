"""工具注册与统一调用 — 扩展新工具时只需 register 即可。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..config import Settings, default_settings
from ..memory.symbol_meta_cache import SymbolMetaCache


def tool_result_ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


def tool_result_err(message: str) -> dict[str, Any]:
    return {"ok": False, "error": message}


ToolFn = Callable[..., dict[str, Any]]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolFn] = {}

    def register(self, name: str, fn: ToolFn) -> None:
        self._tools[name] = fn

    def has(self, name: str) -> bool:
        return name in self._tools

    def call(self, name: str, **kwargs: Any) -> dict[str, Any]:
        if name not in self._tools:
            return tool_result_err(f"unknown_tool:{name}")
        try:
            return tool_result_ok(self._tools[name](**kwargs))
        except TypeError as e:
            return tool_result_err(f"bad_args:{name}:{e}")
        except Exception as e:  # noqa: BLE001 — 工具边界统一吞并
            return tool_result_err(f"tool_error:{name}:{e}")

    def list_names(self) -> list[str]:
        return sorted(self._tools.keys())


def build_default_registry(
    settings: Settings | None = None,
    symbol_meta_cache: SymbolMetaCache | None = None,
) -> ToolRegistry:
    from .mock_data import get_etf_flow, get_etf_price

    cfg = settings if settings is not None else default_settings()
    repo_root = Path(__file__).resolve().parents[2]
    meta_cache = symbol_meta_cache or SymbolMetaCache(
        repo_root / cfg.data_dir / "symbol_meta_cache.json"
    )

    def get_etf_price_tool(etf_code: str) -> dict[str, Any]:
        if getattr(cfg, "use_akshare_daily", False):
            try:
                from .akshare_daily import get_daily_price_snapshot

                return get_daily_price_snapshot(
                    etf_code,
                    include_profile=True,
                    lookback_calendar_days=cfg.akshare_daily_lookback_days,
                    symbol_meta_cache=meta_cache,
                    force_refresh_symbol_meta=False,
                )
            except Exception as e:  # noqa: BLE001
                out = get_etf_price(etf_code)
                out["data_source_fallback"] = True
                out["fallback_reason"] = "akshare_daily"
                out["upstream_error"] = str(e)[:500]
                return out
        return get_etf_price(etf_code)

    def get_etf_flow_tool(etf_code: str) -> dict[str, Any]:
        if getattr(cfg, "use_akshare_daily", False):
            try:
                from .akshare_flow import get_fund_flow_snapshot

                return get_fund_flow_snapshot(etf_code)
            except Exception as e:  # noqa: BLE001
                out = get_etf_flow(etf_code)
                out["data_source_fallback"] = True
                out["fallback_reason"] = "akshare_flow"
                out["upstream_error"] = str(e)[:500]
                return out
        return get_etf_flow(etf_code)

    reg = ToolRegistry()
    reg.register("get_etf_price", get_etf_price_tool)
    reg.register("get_etf_flow", get_etf_flow_tool)
    return reg
