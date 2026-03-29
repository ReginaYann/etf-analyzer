"""将规则结果与（可选）LLM 叙述合并为结构化决策。"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ..llm.client import LLMClient
from .rules import RuleEngine, RuleSignals


class DecisionSynthesizer:
    def __init__(self, llm: LLMClient, rules: RuleEngine | None = None) -> None:
        self._llm = llm
        self._rules = rules or RuleEngine()

    def synthesize(
        self,
        etf_code: str,
        price: dict[str, Any] | None,
        flow: dict[str, Any] | None,
    ) -> dict[str, Any]:
        signals = self._rules.evaluate(price, flow)
        rule_decision, rule_conf = self._rules.suggest_from_rules(signals)

        narrative = self._llm.explain_decision(
            etf_code=etf_code,
            price=price or {},
            flow=flow or {},
            rule_signals=asdict(signals),
            rule_decision=rule_decision,
        )

        # 结构化融合：决策以规则为主，LLM 可微调 confidence（mock 下不变）
        final = self._llm.refine_structured_decision(
            etf_code=etf_code,
            rule_decision=rule_decision,
            rule_confidence=rule_conf,
            rule_signals=signals,
            narrative=narrative,
        )
        final["rule_signals"] = asdict(signals)
        final["llm_note"] = narrative
        return final
