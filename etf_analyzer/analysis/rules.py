"""规则层：不依赖 LLM 的硬逻辑，与 LLM 输出融合形成最终建议。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuleSignals:
    """可序列化进 Memory，便于审计与扩展指标。"""

    price_trend: str  # strong_up / up / flat / down / strong_down
    flow_bias: str  # inflow / neutral / outflow
    score: float  # -1 ~ 1，越大越偏多
    details: dict[str, Any] = field(default_factory=dict)


class RuleEngine:
    """
    简单阈值规则；后续可增加估值分位、成交量、板块轮动等。
    """

    def evaluate(self, price: dict[str, Any] | None, flow: dict[str, Any] | None) -> RuleSignals:
        details: dict[str, Any] = {}
        score = 0.0

        if price:
            pct = float(price.get("change_pct", 0))
            details["change_pct"] = pct
            if pct >= 3:
                trend = "strong_up"
                score += 0.35
            elif pct >= 0.5:
                trend = "up"
                score += 0.2
            elif pct <= -3:
                trend = "strong_down"
                score -= 0.35
            elif pct <= -0.5:
                trend = "down"
                score -= 0.2
            else:
                trend = "flat"
        else:
            trend = "flat"

        if flow:
            main = float(flow.get("main_force_net_wan", 0))
            details["main_force_net_wan"] = main
            if main > 2000:
                fb = "inflow"
                score += 0.35
            elif main < -2000:
                fb = "outflow"
                score -= 0.35
            else:
                fb = "neutral"
        else:
            fb = "neutral"

        score = max(-1.0, min(1.0, score))
        return RuleSignals(price_trend=trend, flow_bias=fb, score=score, details=details)

    def suggest_from_rules(self, signals: RuleSignals) -> tuple[str, float]:
        """
        返回 (decision, confidence_hint)。
        confidence_hint 供 LLM/合成器参考，非最终 confidence。
        """
        s = signals.score
        if s >= 0.45:
            return "buy", min(0.55 + s * 0.3, 0.95)
        if s <= -0.45:
            return "sell", min(0.55 + abs(s) * 0.3, 0.95)
        return "hold", 0.5 + (0.2 - abs(s) * 0.2)
