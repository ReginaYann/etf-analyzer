"""将规则结果与（可选）LLM 叙述合并为结构化决策。"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ..llm.client import LLMClient
from .rules import RuleEngine, RuleSignals


def _enrich_position_context(
    price: dict[str, Any] | None,
    base: dict[str, Any] | None,
) -> dict[str, Any] | None:
    ctx = dict(base) if base else {}
    last = (price or {}).get("last")
    if last is not None:
        try:
            ctx["latest_close_cny"] = float(last)
        except (TypeError, ValueError):
            pass
    ac = ctx.get("avg_cost_cny")
    if ac is not None and ctx.get("latest_close_cny") is not None:
        try:
            acf, lf = float(ac), float(ctx["latest_close_cny"])
            if acf != 0:
                ctx["approx_pnl_pct_vs_cost"] = round((lf - acf) / acf * 100, 4)
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    return ctx or None


class DecisionSynthesizer:
    def __init__(self, llm: LLMClient, rules: RuleEngine | None = None) -> None:
        self._llm = llm
        self._rules = rules or RuleEngine()

    def synthesize(
        self,
        etf_code: str,
        price: dict[str, Any] | None,
        flow: dict[str, Any] | None,
        position_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        signals = self._rules.evaluate(price, flow)
        rule_decision, rule_conf = self._rules.suggest_from_rules(signals)

        pos_ctx = _enrich_position_context(price, position_context)

        narrative = self._llm.explain_decision(
            etf_code=etf_code,
            price=price or {},
            flow=flow or {},
            rule_signals=asdict(signals),
            rule_decision=rule_decision,
            position_context=pos_ctx,
        )

        llm_explain_degraded = narrative.startswith(("[LLM", "[OpenAI"))

        # 结构化融合：决策以规则为主，LLM 可微调 confidence（mock 下不变）
        final = self._llm.refine_structured_decision(
            etf_code=etf_code,
            rule_decision=rule_decision,
            rule_confidence=rule_conf,
            rule_signals=signals,
            narrative=narrative,
            position_context=pos_ctx,
        )
        final["rule_signals"] = asdict(signals)
        final["llm_note"] = narrative
        final["llm_explain_degraded"] = llm_explain_degraded
        if llm_explain_degraded:
            final["llm_explain_error"] = narrative[:800]
        return final
