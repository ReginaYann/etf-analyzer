"""工具注册与统一调用 — 扩展新工具时只需 register 即可。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..config import Settings, default_settings


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


def build_default_registry(settings: Settings | None = None) -> ToolRegistry:
    from .mock_data import get_etf_flow, get_etf_price

    cfg = settings if settings is not None else default_settings()

    def get_etf_price_tool(etf_code: str) -> dict[str, Any]:
        if getattr(cfg, "use_akshare_daily", False):
            try:
                from .akshare_daily import get_daily_price_snapshot

                return get_daily_price_snapshot(etf_code, include_profile=True)
            except Exception:
                pass
        return get_etf_price(etf_code)

    def get_etf_flow_tool(etf_code: str) -> dict[str, Any]:
        if getattr(cfg, "use_akshare_daily", False):
            try:
                from .akshare_flow import get_fund_flow_snapshot

                return get_fund_flow_snapshot(etf_code)
            except Exception:
                pass
        return get_etf_flow(etf_code)

    reg = ToolRegistry()
    reg.register("get_etf_price", get_etf_price_tool)
    reg.register("get_etf_flow", get_etf_flow_tool)
    return reg
