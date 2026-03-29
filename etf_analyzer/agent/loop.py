"""Agent Loop：多步执行 Planner → Tool / Synthesize，直到结束。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..analysis.synthesizer import DecisionSynthesizer
from ..config import Settings, default_settings
from ..memory.store import AnalysisRecord, MemoryStore
from ..tools.registry import ToolRegistry
from .planner import plan_next_step
from .state import AgentState


@dataclass
class AgentStepLog:
    step_index: int
    plan_rationale: str
    action: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunResult:
    etf_code: str
    success: bool
    steps: list[AgentStepLog] = field(default_factory=list)
    synthesis: dict[str, Any] | None = None
    error: str | None = None


class AgentLoop:
    def __init__(
        self,
        tools: ToolRegistry,
        synthesizer: DecisionSynthesizer,
        settings: Settings | None = None,
        memory: MemoryStore | None = None,
    ) -> None:
        self._tools = tools
        self._synthesizer = synthesizer
        self._settings = settings or default_settings()
        self._memory = memory

    def run(
        self,
        etf_code: str,
        *,
        persist_to_memory: bool = True,
        require_flow: bool = True,
    ) -> RunResult:
        code = (etf_code or "").strip().upper()
        if not code:
            return RunResult(etf_code="", success=False, error="empty_etf_code")

        state = AgentState(etf_code=code)
        logs: list[AgentStepLog] = []
        max_steps = self._settings.max_agent_steps

        for _ in range(max_steps):
            plan = plan_next_step(state, require_flow=require_flow)
            if plan.kind == "done":
                break

            if plan.kind == "tool":
                assert plan.tool_name is not None
                raw = self._tools.call(plan.tool_name, **plan.tool_args)
                logs.append(
                    AgentStepLog(
                        step_index=state.step,
                        plan_rationale=plan.rationale,
                        action=f"tool:{plan.tool_name}",
                        payload={"request": plan.tool_args, "result": raw},
                    )
                )
                state.step += 1
                if not raw.get("ok"):
                    err = raw.get("error", "tool_failed")
                    state.note(f"tool_error:{plan.tool_name}:{err}")
                    return RunResult(
                        etf_code=code,
                        success=False,
                        steps=logs,
                        error=str(err),
                    )
                data = raw.get("data")
                if plan.tool_name == "get_etf_price" and isinstance(data, dict):
                    state.price = data
                elif plan.tool_name == "get_etf_flow" and isinstance(data, dict):
                    state.flow = data
                continue

            if plan.kind == "synthesize":
                syn = self._synthesizer.synthesize(
                    etf_code=code,
                    price=state.price,
                    flow=state.flow,
                )
                state.synthesis_result = syn
                logs.append(
                    AgentStepLog(
                        step_index=state.step,
                        plan_rationale=plan.rationale,
                        action="synthesize",
                        payload={"result": syn},
                    )
                )
                state.step += 1

                if persist_to_memory and self._memory is not None:
                    record = AnalysisRecord(
                        etf_code=code,
                        decision=str(syn.get("decision", "hold")),
                        confidence=float(syn.get("confidence", 0.5)),
                        reason=str(syn.get("reason", "")),
                        rule_signals=dict(syn.get("rule_signals") or {}),
                        raw_context={
                            "price": state.price,
                            "flow": state.flow,
                            "llm_note": syn.get("llm_note"),
                        },
                    )
                    self._memory.set_last_analysis(record)

                return RunResult(
                    etf_code=code,
                    success=True,
                    steps=logs,
                    synthesis=syn,
                )

        return RunResult(
            etf_code=code,
            success=False,
            steps=logs,
            error="max_steps_exceeded_or_no_terminal",
        )


def default_memory_path(settings: Settings) -> Path:
    return Path(settings.data_dir) / settings.memory_file
