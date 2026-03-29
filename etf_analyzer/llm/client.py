"""LLM 抽象：Mock 与 OpenAI 可插拔。"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from ..analysis.rules import RuleSignals


class LLMClient(ABC):
    @abstractmethod
    def explain_decision(
        self,
        etf_code: str,
        price: dict[str, Any],
        flow: dict[str, Any],
        rule_signals: dict[str, Any],
        rule_decision: str,
    ) -> str:
        pass

    @abstractmethod
    def refine_structured_decision(
        self,
        etf_code: str,
        rule_decision: str,
        rule_confidence: float,
        rule_signals: RuleSignals,
        narrative: str,
    ) -> dict[str, Any]:
        pass


class MockLLMClient(LLMClient):
    """不调用外网；生成可读说明，结构化字段与规则对齐。"""

    def explain_decision(
        self,
        etf_code: str,
        price: dict[str, Any],
        flow: dict[str, Any],
        rule_signals: dict[str, Any],
        rule_decision: str,
    ) -> str:
        label = price.get("security_name") or etf_code
        meta_bits = []
        if price.get("asset_type"):
            meta_bits.append(f"类型={price.get('asset_type')}")
        if price.get("industry"):
            meta_bits.append(f"行业={price.get('industry')}")
        if price.get("sector"):
            meta_bits.append(f"板块={price.get('sector')}")
        meta_s = ("（" + "，".join(meta_bits) + "）") if meta_bits else ""
        parts = [f"[MockLLM] 标的 {label}{meta_s}：规则倾向 {rule_decision}。"]
        if price:
            parts.append(
                f"价格涨跌 {price.get('change_pct')}% ，最新价 {price.get('last')}。"
            )
        if flow:
            src = flow.get("source", "mock")
            fd = flow.get("flow_date")
            fd_s = f"，日期{fd}" if fd else ""
            parts.append(
                f"主力净流入约 {flow.get('main_force_net_wan')} 万元（{src}{fd_s}）。"
            )
        parts.append(f"规则信号：趋势={rule_signals.get('price_trend')}，资金流={rule_signals.get('flow_bias')}。")
        return " ".join(parts)

    def refine_structured_decision(
        self,
        etf_code: str,
        rule_decision: str,
        rule_confidence: float,
        rule_signals: RuleSignals,
        narrative: str,
    ) -> dict[str, Any]:
        # Mock：完全尊重规则决策，仅略抖动 confidence 展示“融合”接口
        conf = round(min(0.95, max(0.35, rule_confidence + 0.02)), 2)
        return {
            "decision": rule_decision,
            "confidence": conf,
            "reason": narrative[:500],
            "etf_code": etf_code,
        }


class OpenAILLMClient(LLMClient):
    """可选：需要 openai 包与 API Key。失败时回退为规则决策。"""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        self._api_key = api_key
        self._model = model

    def explain_decision(
        self,
        etf_code: str,
        price: dict[str, Any],
        flow: dict[str, Any],
        rule_signals: dict[str, Any],
        rule_decision: str,
    ) -> str:
        try:
            from openai import OpenAI

            client = OpenAI(api_key=self._api_key)
            user_payload = {
                "etf_code": etf_code,
                "price": price,
                "flow": flow,
                "rule_signals": rule_signals,
                "rule_decision": rule_decision,
            }
            r = client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是严谨的ETF分析助手，用中文简短说明，不要编造未知数据。",
                    },
                    {
                        "role": "user",
                        "content": json.dumps(user_payload, ensure_ascii=False),
                    },
                ],
                temperature=0.3,
            )
            return (r.choices[0].message.content or "").strip()
        except Exception as e:  # noqa: BLE001
            return f"[OpenAI 不可用，回退说明] {e}"

    def refine_structured_decision(
        self,
        etf_code: str,
        rule_decision: str,
        rule_confidence: float,
        rule_signals: RuleSignals,
        narrative: str,
    ) -> dict[str, Any]:
        schema_hint = (
            '{"decision":"buy|sell|hold","confidence":0.0-1.0,"reason":"..."}'
        )
        try:
            from openai import OpenAI

            client = OpenAI(api_key=self._api_key)
            r = client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": f"输出仅一行合法 JSON，键为 decision, confidence, reason。{schema_hint}",
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "etf_code": etf_code,
                                "rule_decision": rule_decision,
                                "rule_confidence": rule_confidence,
                                "rule_signals": {
                                    "price_trend": rule_signals.price_trend,
                                    "flow_bias": rule_signals.flow_bias,
                                    "score": rule_signals.score,
                                },
                                "narrative": narrative,
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                temperature=0.2,
            )
            text = (r.choices[0].message.content or "").strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            parsed = json.loads(text)
            dec = str(parsed.get("decision", rule_decision)).lower()
            if dec not in ("buy", "sell", "hold"):
                dec = rule_decision
            conf = float(parsed.get("confidence", rule_confidence))
            conf = min(0.95, max(0.2, conf))
            return {
                "decision": dec,
                "confidence": round(conf, 2),
                "reason": str(parsed.get("reason", narrative))[:800],
                "etf_code": etf_code,
            }
        except Exception:
            return {
                "decision": rule_decision,
                "confidence": round(rule_confidence, 2),
                "reason": narrative[:500],
                "etf_code": etf_code,
            }


def create_llm_client(use_mock: bool, api_key: str | None, model: str) -> LLMClient:
    if use_mock or not api_key:
        return MockLLMClient()
    return OpenAILLMClient(api_key=api_key, model=model)
