"""用户交易偏好：解析配置并生成注入大模型的系统提示片段。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _to_tuple_str(v: Any) -> tuple[str, ...]:
    if v is None:
        return ()
    if isinstance(v, str):
        return tuple(s.strip() for s in v.split(",") if s.strip())
    if isinstance(v, (list, tuple)):
        return tuple(str(x).strip() for x in v if str(x).strip())
    return ()


@dataclass(frozen=True)
class TradingPreferences:
    """
    个性化交易约束；大模型在 explain / refine 阶段必须遵守。
    所有字段均可选，未填则不在提示中强调。
    """

    risk_tolerance: str = ""
    """conservative / moderate / aggressive 或自定义中文描述"""

    investment_horizon: str = ""
    """如 long_term / swing / short_term 或自定义"""

    max_single_position_pct: float | None = None
    """单标的占组合比例上限（百分比数字，如 15 表示 15%）"""

    avoid_industries: tuple[str, ...] = field(default_factory=tuple)
    avoid_keywords: tuple[str, ...] = field(default_factory=tuple)
    focus_themes: tuple[str, ...] = field(default_factory=tuple)

    must_follow_text: str = ""
    """自由文本，强制遵守的规则（多行）"""

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> TradingPreferences:
        if not d:
            return cls()
        pct = d.get("max_single_position_pct")
        pct_f: float | None
        if pct is None or pct == "":
            pct_f = None
        else:
            try:
                pct_f = float(pct)
            except (TypeError, ValueError):
                pct_f = None
        return cls(
            risk_tolerance=str(d.get("risk_tolerance") or "").strip(),
            investment_horizon=str(d.get("investment_horizon") or "").strip(),
            max_single_position_pct=pct_f,
            avoid_industries=_to_tuple_str(d.get("avoid_industries")),
            avoid_keywords=_to_tuple_str(d.get("avoid_keywords")),
            focus_themes=_to_tuple_str(d.get("focus_themes")),
            must_follow_text=str(d.get("must_follow_text") or "").strip(),
        )

    def is_empty(self) -> bool:
        return (
            not self.risk_tolerance
            and not self.investment_horizon
            and self.max_single_position_pct is None
            and not self.avoid_industries
            and not self.avoid_keywords
            and not self.focus_themes
            and not self.must_follow_text
        )

    def to_dict(self) -> dict[str, Any]:
        """供 API / JSON 持久化。"""
        return {
            "risk_tolerance": self.risk_tolerance,
            "investment_horizon": self.investment_horizon,
            "max_single_position_pct": self.max_single_position_pct,
            "avoid_industries": list(self.avoid_industries),
            "avoid_keywords": list(self.avoid_keywords),
            "focus_themes": list(self.focus_themes),
            "must_follow_text": self.must_follow_text,
        }

    def to_system_prompt_block(self) -> str:
        """注入 system 角色，要求模型严格遵守。"""
        if self.is_empty():
            return (
                "【用户交易偏好】用户未配置额外偏好；仍须基于给定数据客观分析，"
                "decision 仅能为 buy、sell、hold 之一，不得编造行情。"
            )
        lines = [
            "【用户交易偏好 — 强制遵守】",
            "以下约束优先级高于一般市场建议；你的结构化决策（buy/sell/hold）与理由必须与之一致。",
            "若行情数据与用户偏好冲突（例如在规避行业内），应倾向 hold 或 sell，并在 reason 中明确说明冲突。",
        ]
        if self.risk_tolerance:
            lines.append(f"- 风险承受：{self.risk_tolerance}")
        if self.investment_horizon:
            lines.append(f"- 投资周期/风格：{self.investment_horizon}")
        if self.max_single_position_pct is not None:
            lines.append(f"- 单标的仓位上限（概念上）：不超过组合的 {self.max_single_position_pct}%")
        if self.avoid_industries:
            lines.append(f"- 规避行业（涉及则应偏谨慎或 hold/sell）：{', '.join(self.avoid_industries)}")
        if self.avoid_keywords:
            lines.append(f"- 规避关键词/标的特征：{', '.join(self.avoid_keywords)}")
        if self.focus_themes:
            lines.append(f"- 关注方向（在数据支持时可作为加分项，但不得编造）：{', '.join(self.focus_themes)}")
        if self.must_follow_text:
            lines.append("- 用户自定义硬性规则：")
            lines.append(self.must_follow_text)
        return "\n".join(lines)
