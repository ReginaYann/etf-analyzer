"""FastAPI：自选 CRUD + 触发 Agent 分析；挂载静态前端。"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..agent.loop import AgentLoop, RunResult
from ..analysis.rules import RuleEngine
from ..analysis.synthesizer import DecisionSynthesizer
from ..config import Settings, default_settings
from ..llm.client import create_llm_client
from ..memory.store import MemoryStore
from ..tools.registry import build_default_registry


def _project_root() -> Path:
    # etf_analyzer/web/app.py -> parents[2] = 仓库根目录
    return Path(__file__).resolve().parents[2]


def _memory_store(settings: Settings) -> MemoryStore:
    root = _project_root()
    mem_path = root / settings.data_dir / settings.memory_file
    return MemoryStore(mem_path)


def _build_agent(memory: MemoryStore, settings: Settings) -> AgentLoop:
    tools = build_default_registry()
    llm = create_llm_client(
        use_mock=settings.use_mock_llm,
        api_key=settings.openai_api_key,
        model=settings.openai_model,
    )
    synthesizer = DecisionSynthesizer(llm=llm, rules=RuleEngine())
    return AgentLoop(
        tools=tools,
        synthesizer=synthesizer,
        settings=settings,
        memory=memory,
    )


def _run_result_to_json(r: RunResult) -> dict:
    return {
        "success": r.success,
        "etf_code": r.etf_code,
        "error": r.error,
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


class WatchlistItemPatch(BaseModel):
    name: str | None = None
    asset_type: str | None = None


class WatchlistReorder(BaseModel):
    codes: list[str] = Field(..., description="按期望顺序排列的代码列表")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or default_settings()
    memory = _memory_store(settings)

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
        items = [
            {"code": i.code, "name": i.name, "asset_type": i.asset_type}
            for i in memory.watchlist_items
        ]
        return {"items": items}

    @app.post("/api/watchlist")
    def add_watchlist_item(body: WatchlistItemCreate) -> dict:
        try:
            item = memory.add_watchlist_item(
                body.code,
                name=body.name,
                asset_type=body.asset_type,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"ok": True, "item": item.to_dict()}

    @app.patch("/api/watchlist/{code}")
    def patch_watchlist_item(code: str, body: WatchlistItemPatch) -> dict:
        updated = memory.update_watchlist_item(
            code,
            name=body.name,
            asset_type=body.asset_type,
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

    @app.post("/api/analyze/{code}")
    def analyze(code: str) -> dict:
        agent = _build_agent(memory, settings)
        result = agent.run(code.strip(), persist_to_memory=True)
        return _run_result_to_json(result)

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
