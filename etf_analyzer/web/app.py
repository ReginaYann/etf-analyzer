"""FastAPI：自选 CRUD + 触发 Agent 分析；挂载静态前端。"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..agent.loop import AgentLoop, RunResult
from ..analysis.rules import RuleEngine
from ..analysis.synthesizer import DecisionSynthesizer
from ..config import (
    TRADING_PREFERENCES_JSON,
    Settings,
    default_settings,
    load_effective_settings,
)
from ..llm.client import create_llm_client
from ..memory.store import MemoryStore
from ..memory.symbol_meta_cache import SymbolMetaCache
from ..tools.akshare_meta import fetch_security_profile
from ..tools.registry import build_default_registry


def _project_root() -> Path:
    # etf_analyzer/web/app.py -> parents[2] = 仓库根目录
    return Path(__file__).resolve().parents[2]


def _memory_store(settings: Settings) -> MemoryStore:
    root = _project_root()
    mem_path = root / settings.data_dir / settings.memory_file
    return MemoryStore(mem_path)


def _symbol_meta_cache(settings: Settings) -> SymbolMetaCache:
    root = _project_root()
    return SymbolMetaCache(root / settings.data_dir / "symbol_meta_cache.json")


def _build_agent(
    memory: MemoryStore,
    settings: Settings,
    symbol_meta: SymbolMetaCache,
) -> AgentLoop:
    tools = build_default_registry(settings, symbol_meta_cache=symbol_meta)
    llm = create_llm_client(settings)
    synthesizer = DecisionSynthesizer(llm=llm, rules=RuleEngine())
    return AgentLoop(
        tools=tools,
        synthesizer=synthesizer,
        settings=settings,
        memory=memory,
    )


def _collect_user_issues(r: RunResult) -> list[dict]:
    """供前端展示：AKShare 回退、LLM 异常、Agent 失败等。"""
    issues: list[dict] = []
    if not r.success:
        issues.append(
            {
                "level": "error",
                "code": "agent_failed",
                "title": "分析未能完成",
                "detail": r.error or "未知错误",
            }
        )
        return issues

    for s in r.steps:
        if not str(s.action).startswith("tool:"):
            continue
        payload = s.payload or {}
        res = payload.get("result") or {}
        if not res.get("ok"):
            issues.append(
                {
                    "level": "error",
                    "code": "tool_failed",
                    "title": f"工具失败：{s.action}",
                    "detail": str(res.get("error", "")),
                }
            )
            continue
        data = res.get("data") or {}
        if data.get("data_source_fallback"):
            reason = data.get("fallback_reason") or ""
            if reason == "akshare_daily":
                title = "AKShare 日线/档案失败，已改用模拟行情"
            elif reason == "akshare_flow":
                title = "AKShare 资金流向失败，已改用模拟资金流"
            else:
                title = "数据源回退为模拟数据"
            issues.append(
                {
                    "level": "warning",
                    "code": "akshare_fallback",
                    "title": title,
                    "detail": str(data.get("upstream_error", "")).strip() or "无详细错误信息",
                }
            )

    syn = r.synthesis or {}
    if syn.get("llm_explain_degraded"):
        issues.append(
            {
                "level": "warning",
                "code": "llm_explain_degraded",
                "title": "大模型解释阶段异常（已使用回退说明）",
                "detail": str(syn.get("llm_explain_error") or syn.get("llm_note", ""))[:600],
            }
        )
    if syn.get("llm_refine_failed"):
        issues.append(
            {
                "level": "warning",
                "code": "llm_refine_failed",
                "title": "大模型结构化输出失败（决策已回退为规则结果）",
                "detail": str(syn.get("llm_refine_error", "")),
            }
        )

    return issues


def _run_result_to_json(r: RunResult) -> dict:
    return {
        "success": r.success,
        "etf_code": r.etf_code,
        "error": r.error,
        "issues": _collect_user_issues(r),
        "synthesis": r.synthesis,
        "steps": [
            {
                "step_index": s.step_index,
                "plan_rationale": s.plan_rationale,
                "action": s.action,
                "payload": s.payload,
            }
            for s in r.steps
        ],
    }


class WatchlistItemCreate(BaseModel):
    code: str = Field(..., min_length=1, description="证券代码，如 510300、600000")
    name: str = ""
    asset_type: str = Field(
        "auto",
        description="auto | stock | etf",
    )
    position_cost: float | None = None
    position_quantity: float | None = None
    notes: str = ""


class WatchlistItemPatch(BaseModel):
    name: str | None = None
    asset_type: str | None = None
    position_cost: float | None = None
    position_quantity: float | None = None
    notes: str | None = None


class WatchlistHoldingUpdate(BaseModel):
    """持仓成本、数量、备注（可单独保存，null 清空成本/数量）。"""

    position_cost: float | None = None
    position_quantity: float | None = None
    notes: str = ""


class TradingPreferencesUpdate(BaseModel):
    risk_tolerance: str = ""
    investment_horizon: str = ""
    max_single_position_pct: float | None = None
    avoid_industries: list[str] = Field(default_factory=list)
    avoid_keywords: list[str] = Field(default_factory=list)
    focus_themes: list[str] = Field(default_factory=list)
    must_follow_text: str = ""


class WatchlistReorder(BaseModel):
    codes: list[str] = Field(..., description="按期望顺序排列的代码列表")


class SymbolMetaRefreshBody(BaseModel):
    codes: list[str] | None = Field(
        None,
        description="要刷新的代码；省略则刷新当前自选全部",
    )


def _cached_meta_view(row: dict | None) -> dict | None:
    if row is None:
        return None
    conc = str(row.get("concept") or "")
    return {
        "security_name": str(row.get("name") or ""),
        "industry": str(row.get("industry") or ""),
        "sector": str(row.get("sector") or ""),
        "concept_board": conc[:160] + ("…" if len(conc) > 160 else ""),
        "listing_board": str(row.get("listing_board") or ""),
        "fund_type_detail": str(row.get("fund_type_detail") or ""),
        "updated_at": row.get("updated_at"),
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = load_effective_settings(settings)
    memory = _memory_store(settings)
    symbol_meta = _symbol_meta_cache(settings)

    def _prefs_path() -> Path:
        return _project_root() / settings.data_dir / TRADING_PREFERENCES_JSON

    def _reload_settings() -> Settings:
        return load_effective_settings(default_settings())

    app = FastAPI(
        title="ETF / 股票分析 Agent",
        version="0.2.0",
        description="自选配置与 Agent 分析 API",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    static_dir = _project_root() / "static"
    if static_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(static_dir)), name="assets")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/watchlist")
    def list_watchlist() -> dict:
        items = []
        for i in memory.watchlist_items:
            row = symbol_meta.get(i.code)
            items.append(
                {
                    "code": i.code,
                    "name": i.name,
                    "asset_type": i.asset_type,
                    "position_cost": i.position_cost,
                    "position_quantity": i.position_quantity,
                    "notes": i.notes,
                    "cached_meta": _cached_meta_view(row),
                }
            )
        return {"items": items}

    @app.post("/api/watchlist")
    def add_watchlist_item(body: WatchlistItemCreate) -> dict:
        try:
            item = memory.add_watchlist_item(
                body.code,
                name=body.name,
                asset_type=body.asset_type,
                position_cost=body.position_cost,
                position_quantity=body.position_quantity,
                notes=body.notes,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"ok": True, "item": item.to_dict()}

    @app.patch("/api/watchlist/{code}")
    def patch_watchlist_item(code: str, body: WatchlistItemPatch) -> dict:
        patch = body.model_dump(exclude_unset=True)
        updated = memory.update_watchlist_item_from_patch(code, patch)
        if updated is None:
            raise HTTPException(status_code=404, detail="code not in watchlist")
        return {"ok": True, "item": updated.to_dict()}

    @app.put("/api/watchlist/{code}/holding")
    def put_watchlist_holding(code: str, body: WatchlistHoldingUpdate) -> dict:
        updated = memory.update_watchlist_item_from_patch(
            code,
            body.model_dump(),
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="code not in watchlist")
        return {"ok": True, "item": updated.to_dict()}

    @app.delete("/api/watchlist/{code}")
    def delete_watchlist_item(code: str) -> dict:
        if not memory.remove_watchlist_item(code):
            raise HTTPException(status_code=404, detail="code not in watchlist")
        return {"ok": True}

    @app.put("/api/watchlist/reorder")
    def reorder_watchlist(body: WatchlistReorder) -> dict:
        memory.reorder_watchlist(body.codes)
        return list_watchlist()

    @app.post("/api/symbol-meta/refresh")
    def refresh_symbol_meta(body: SymbolMetaRefreshBody = SymbolMetaRefreshBody()) -> dict:
        raw_codes = body.codes or [i.code for i in memory.watchlist_items]
        errors: list[dict[str, str]] = []
        attempted = 0
        for c in raw_codes:
            code = str(c or "").strip()
            if not code:
                continue
            attempted += 1
            try:
                fetch_security_profile(
                    code,
                    cache=symbol_meta,
                    force_refresh=True,
                )
            except Exception as e:  # noqa: BLE001
                errors.append({"code": code, "error": str(e)[:500]})
        return {
            "ok": True,
            "refreshed": max(0, attempted - len(errors)),
            "errors": errors,
        }

    @app.get("/api/trading-preferences")
    def get_trading_preferences() -> dict:
        eff = _reload_settings()
        return {"preferences": eff.trading_preferences.to_dict()}

    @app.put("/api/trading-preferences")
    def put_trading_preferences(body: TradingPreferencesUpdate) -> dict:
        path = _prefs_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = body.model_dump()
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        eff = _reload_settings()
        return {"ok": True, "preferences": eff.trading_preferences.to_dict()}

    @app.post("/api/analyze/{code}")
    def analyze(code: str) -> dict:
        try:
            eff = _reload_settings()
            agent = _build_agent(memory, eff, symbol_meta)
            result = agent.run(code.strip(), persist_to_memory=True)
            return _run_result_to_json(result)
        except Exception as e:  # noqa: BLE001
            return {
                "success": False,
                "etf_code": code.strip(),
                "error": f"server_exception:{e!s}",
                "issues": [
                    {
                        "level": "error",
                        "code": "server_exception",
                        "title": "服务端异常",
                        "detail": str(e),
                    }
                ],
                "synthesis": None,
                "steps": [],
            }

    @app.get("/api/last-analysis")
    def last_analysis() -> dict:
        la = memory.last_analysis
        if la is None:
            return {"analysis": None}
        return {"analysis": la.to_dict()}

    index_file = static_dir / "index.html"

    @app.get("/")
    def spa_index():
        if index_file.is_file():
            return FileResponse(str(index_file))
        return {
            "message": "静态页未找到。请在项目根目录创建 static/index.html，或访问 /docs",
        }

    return app
