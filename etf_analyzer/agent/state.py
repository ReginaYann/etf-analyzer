"""Agent 运行态：已收集的数据与步数，供 Planner 决策。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentState:
    etf_code: str
    step: int = 0
    price: dict[str, Any] | None = None
    flow: dict[str, Any] | None = None
    # 分析完成后写入，便于扩展多轮分析或日志回放
    synthesis_result: dict[str, Any] | None = None
    scratchpad: list[str] = field(default_factory=list)

    def note(self, msg: str) -> None:
        self.scratchpad.append(msg)

    def has_price(self) -> bool:
        return self.price is not None

    def has_flow(self) -> bool:
        return self.flow is not None
