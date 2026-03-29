"""
最小可运行 Demo：添加自选 -> Agent 多步拉数 -> 规则+LLM 结构化结论。
在项目根目录执行: python main.py
"""

from __future__ import annotations

import json
from pathlib import Path

from etf_analyzer.agent.loop import AgentLoop
from etf_analyzer.analysis.synthesizer import DecisionSynthesizer
from etf_analyzer.analysis.rules import RuleEngine
from etf_analyzer.config import default_settings
from etf_analyzer.llm.client import create_llm_client
from etf_analyzer.memory.store import MemoryStore
from etf_analyzer.tools.registry import build_default_registry


def main() -> None:
    settings = default_settings()
    data_root = Path(__file__).resolve().parent / settings.data_dir
    mem_path = data_root / settings.memory_file
    memory = MemoryStore(mem_path)

    # 1) 添加 ETF 到自选
    demo_code = "510300"
    memory.add_etf(demo_code)
    print("当前自选:", memory.watchlist)

    # 2) 组装 Agent（工具注册表 + 合成器 + Loop）
    tools = build_default_registry(settings)
    llm = create_llm_client(
        use_mock=settings.use_mock_llm,
        api_key=settings.openai_api_key,
        model=settings.openai_model,
    )
    synthesizer = DecisionSynthesizer(llm=llm, rules=RuleEngine())
    agent = AgentLoop(
        tools=tools,
        synthesizer=synthesizer,
        settings=settings,
        memory=memory,
    )

    # 3) 运行多步 Agent：先价格、再资金流、再合成
    result = agent.run(demo_code, persist_to_memory=True)
    if not result.success:
        print("运行失败:", result.error)
        return

    out = result.synthesis or {}
    print("\n=== 结构化决策 ===")
    print(
        json.dumps(
            {
                "decision": out.get("decision"),
                "confidence": out.get("confidence"),
                "reason": out.get("reason"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    la = memory.last_analysis
    if la:
        print("\nMemory 中最近一次分析:", la.etf_code, la.decision, la.confidence)

    print("\n=== Agent 步进轨迹 ===")
    for log in result.steps:
        print(f"  [{log.step_index}] {log.action}: {log.plan_rationale}")


if __name__ == "__main__":
    main()
