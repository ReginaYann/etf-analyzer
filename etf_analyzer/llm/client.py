"""LLM 抽象：Mock 与 OpenAI 兼容 API（ChatGPT、DeepSeek、Moonshot 等）。"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from ..analysis.rules import RuleSignals
from ..config import Settings


class LLMClient(ABC):
    @abstractmethod
    def explain_decision(
        self,
        etf_code: str,
        price: dict[str, Any],
        flow: dict[str, Any],
        rule_signals: dict[str, Any],
        rule_decision: str,
        position_context: dict[str, Any] | None = None,
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
        position_context: dict[str, Any] | None = None,
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
        position_context: dict[str, Any] | None = None,
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
        if position_context:
            parts.append(f"用户持仓与备注（供参考）：{json.dumps(position_context, ensure_ascii=False)}")
        return " ".join(parts)

    def refine_structured_decision(
        self,
        etf_code: str,
        rule_decision: str,
        rule_confidence: float,
        rule_signals: RuleSignals,
        narrative: str,
        position_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        conf = round(min(0.95, max(0.35, rule_confidence + 0.02)), 2)
        reason = narrative[:500]
        if position_context:
            tag = "（已含用户持仓/备注上下文）"
            reason = (reason + tag)[:500]
        return {
            "decision": rule_decision,
            "confidence": conf,
            "reason": reason,
            "etf_code": etf_code,
        }


def _strip_json_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return t


class OpenAICompatibleLLMClient(LLMClient):
    """
    任意 OpenAI Chat Completions 兼容接口：官方 OpenAI、DeepSeek、Moonshot、智谱等。
    通过 base_url + model 切换服务商。
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
        trading_preferences: "TradingPreferences | None" = None,
    ) -> None:
        from ..trading_preferences import TradingPreferences as TP

        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._prefs = trading_preferences or TP()

    def _client(self) -> Any:
        from openai import OpenAI

        kwargs: dict[str, Any] = {"api_key": self._api_key}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        return OpenAI(**kwargs)

    def _system_explain(self) -> str:
        return "\n\n".join(
            [
                self._prefs.to_system_prompt_block(),
                "你是有合规意识的证券投资分析助手。仅用用户 JSON 里提供的数据发言，不得编造未知行情或新闻。用中文简练输出一段分析叙述。",
                "若用户 JSON 中含 user_position（持仓成本、数量、备注等），须结合 price 中的最新价与成本对比讨论盈亏与风险（仅基于给定数字），并尊重用户备注；不得臆造未提供的字段。",
            ]
        )

    def _system_refine(self) -> str:
        schema = '{"decision":"buy|sell|hold","confidence":0.0-1.0,"reason":"..."}'
        return "\n\n".join(
            [
                self._prefs.to_system_prompt_block(),
                "在严格遵守上述用户交易偏好的前提下，结合规则参考结论与叙述，输出最终结构化结论。",
                f"输出仅一行合法 JSON，键为 decision, confidence, reason。{schema}",
                "decision 只能为小写 buy、sell、hold；若用户偏好要求规避或降风险，应体现在 decision 与 reason 中。",
                "若 user JSON 含 user_position，结构化结论须体现对持仓成本、盈亏（若有数据）与用户备注的考量。",
            ]
        )

    def explain_decision(
        self,
        etf_code: str,
        price: dict[str, Any],
        flow: dict[str, Any],
        rule_signals: dict[str, Any],
        rule_decision: str,
        position_context: dict[str, Any] | None = None,
    ) -> str:
        try:
            client = self._client()
            user_payload: dict[str, Any] = {
                "etf_code": etf_code,
                "price": price,
                "flow": flow,
                "rule_signals": rule_signals,
                "rule_decision": rule_decision,
            }
            if position_context:
                user_payload["user_position"] = position_context
            r = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": self._system_explain()},
                    {
                        "role": "user",
                        "content": json.dumps(user_payload, ensure_ascii=False),
                    },
                ],
                temperature=0.3,
            )
            return (r.choices[0].message.content or "").strip()
        except Exception as e:  # noqa: BLE001
            return f"[LLM 调用失败，回退说明] {e}"

    def refine_structured_decision(
        self,
        etf_code: str,
        rule_decision: str,
        rule_confidence: float,
        rule_signals: RuleSignals,
        narrative: str,
        position_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            client = self._client()
            refine_user: dict[str, Any] = {
                "etf_code": etf_code,
                "rule_decision": rule_decision,
                "rule_confidence": rule_confidence,
                "rule_signals": {
                    "price_trend": rule_signals.price_trend,
                    "flow_bias": rule_signals.flow_bias,
                    "score": rule_signals.score,
                },
                "narrative": narrative,
            }
            if position_context:
                refine_user["user_position"] = position_context
            r = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": self._system_refine()},
                    {
                        "role": "user",
                        "content": json.dumps(refine_user, ensure_ascii=False),
                    },
                ],
                temperature=0.2,
            )
            text = _strip_json_fence(r.choices[0].message.content or "")
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
        except Exception as e:  # noqa: BLE001
            return {
                "decision": rule_decision,
                "confidence": round(rule_confidence, 2),
                "reason": narrative[:500],
                "etf_code": etf_code,
                "llm_refine_failed": True,
                "llm_refine_error": str(e)[:400],
            }


# 旧名兼容
OpenAILLMClient = OpenAICompatibleLLMClient


def create_llm_client(settings: Settings) -> LLMClient:
    if settings.use_mock_llm or not settings.api_key:
        return MockLLMClient()
    return OpenAICompatibleLLMClient(
        api_key=settings.api_key,
        model=settings.model_name,
        base_url=settings.model_url,
        trading_preferences=settings.trading_preferences,
    )
