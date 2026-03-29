"""
Planner：根据当前已知信息决定下一步（工具 / 综合分析）。
不调用 LLM，保证可测、可替换为更复杂的策略或 LLM-planner。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .state import AgentState

PlanKind = Literal["tool", "synthesize", "done"]


@dataclass(frozen=True)
class Plan:
    kind: PlanKind
    tool_name: str | None = None
    tool_args: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""


def plan_next_step(state: AgentState, require_flow: bool = True) -> Plan:
    """
    决策是否需要更多信息：
    - 无价格 -> 拉价格
    - 有价格、需要资金流且无资金流 -> 拉资金流
    - 否则进入规则+LLM 合成（可扩展为「仅价格先给初步结论再拉资金流」）
    """
    if state.synthesis_result is not None:
        return Plan(kind="done", rationale="已完成分析")

    if not state.has_price():
        return Plan(
            kind="tool",
            tool_name="get_etf_price",
            tool_args={"etf_code": state.etf_code},
            rationale="缺少行情，需调用 get_etf_price",
        )

    if require_flow and not state.has_flow():
        return Plan(
            kind="tool",
            tool_name="get_etf_flow",
            tool_args={"etf_code": state.etf_code},
            rationale="缺少资金流向，需调用 get_etf_flow",
        )

    return Plan(
        kind="synthesize",
        rationale="已具备分析所需数据，执行规则+LLM 合成",
    )
