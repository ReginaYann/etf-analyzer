# ETF 分析 Agent

可扩展的 **Agent 架构**（多步循环 + 工具调用 + Memory + 规则与 LLM 合成），用于管理自选 ETF、拉取（当前为 Mock）数据，并输出结构化的 `buy` / `sell` / `hold` 建议。

## 能力概览

- **自选管理**：添加 / 删除 / 查看（`MemoryStore` + JSON 持久化）
- **数据工具**：`get_etf_price`、`get_etf_flow`（Mock，可替换为真实行情 API）
- **分析**：`RuleEngine` 阈值打分 + `DecisionSynthesizer` 与 LLM（Mock 或 OpenAI）合成结论
- **多步 Agent**：`Planner` 根据已有信息决定下一步是拉价格、拉资金流还是进入综合分析，而非单次调用模型

## 项目结构

```
etf-analyzer/
├── main.py                 # 最小 Demo 入口
├── pyproject.toml          # 包元数据与可选依赖 [llm]
├── requirements.txt        # 说明（默认无强依赖；OpenAI 见下文）
├── README.md
├── data/                   # 运行后生成：watchlist_memory.json
└── etf_analyzer/
    ├── __init__.py
    ├── config.py           # 路径、LLM、步数上限等
    ├── agent/
    │   ├── state.py        # Agent 运行态（已拉取的价格/资金流等）
    │   ├── planner.py      # 下一步动作规划（不调用 LLM，可替换策略）
    │   └── loop.py         # Agent Loop：Plan → Tool / Synthesize
    ├── tools/
    │   ├── mock_data.py    # Mock 行情与资金流
    │   └── registry.py     # 工具注册与统一调用
    ├── memory/
    │   └── store.py        # 自选列表 + 最近一次分析记录
    ├── analysis/
    │   ├── rules.py        # 规则层信号与粗决策
    │   └── synthesizer.py  # 规则 + LLM 结构化输出
    └── llm/
        └── client.py       # MockLLMClient / OpenAILLMClient
```

## 环境要求

- Python 3.10+

## 安装与运行

在项目根目录：

```bash
pip install -e .
python main.py
```

若不安装为包，可临时设置 `PYTHONPATH` 指向项目根目录后再执行 `python main.py`。

Demo 会向自选加入 `510300`，跑一轮 Agent（先价格工具、再资金流工具、再合成），并在终端打印结构化决策与步进说明；数据写入 `data/watchlist_memory.json`。

## 环境变量

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` | 设置且关闭 Mock 时使用 OpenAI |
| `ETF_USE_MOCK_LLM` | `0` / `false` / `no`：在已配置 Key 时尝试走 `OpenAILLMClient`（需安装 `openai`） |

安装 OpenAI 可选依赖：

```bash
pip install -e ".[llm]"
```

## 输出格式（结构化决策）

合成结果中包含例如：

```json
{
  "decision": "buy",
  "confidence": 0.72,
  "reason": "..."
}
```

完整字典中还可包含 `rule_signals`、`llm_note` 等，便于扩展与审计。

## 扩展建议

- **真实数据**：实现与 `mock_data.py` 相同签名的函数，在 `build_default_registry()` 中注册或替换工具名。
- **新指标**：在 `RuleEngine.evaluate` 中增加字段，并在 `MemoryStore.AnalysisRecord` 中持久化需要的部分。
- **更强 Planner**：将 `plan_next_step` 替换为基于 LLM 的规划器，仍通过 `ToolRegistry.call` 执行工具，保持 Loop 形状不变。

## 许可证

按你的需要自行补充（当前仓库未默认指定）。
