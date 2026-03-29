# ETF 分析 Agent

可扩展的 **Agent 架构**（多步循环 + 工具调用 + Memory + 规则与 LLM 合成），用于管理自选 ETF、拉取（当前为 Mock）数据，并输出结构化的 `buy` / `sell` / `hold` 建议。

## 能力概览

- **自选管理**：添加 / 删除 / 查看 / 重排序；支持名称与类型（`stock` / `etf` / `auto`），持久化为 `watchlist_items`（兼容旧版纯代码列表）
- **数据工具**：`get_etf_price`（AKShare **日线** + **名称/类型/行业板块** 等，失败回退 Mock）、`get_etf_flow`（AKShare **东财资金流向** 最新一日，失败回退 Mock）
- **分析**：`RuleEngine` 阈值打分 + `DecisionSynthesizer` 与 LLM（Mock 或 OpenAI）合成结论
- **多步 Agent**：`Planner` 根据已有信息决定下一步是拉价格、拉资金流还是进入综合分析，而非单次调用模型

## 项目结构

```
etf-analyzer/
├── main.py                 # 最小 Demo 入口
├── run_web.py              # FastAPI + 静态页：python run_web.py
├── static/                 # 简单前端（自选表单、列表、分析）
├── pyproject.toml          # 可选依赖 [llm]、[web]
├── requirements.txt
├── README.md
├── etf_config.example.yaml # 复制为 etf_config.yaml；含 LLM 与 trading_preferences
├── .env.example            # 复制为 .env 存放密钥（已 gitignore）
├── data/                   # 运行后生成：watchlist_memory.json
└── etf_analyzer/
    ├── __init__.py
    ├── config.py              # 读取 etf_config.yaml + .env + 环境变量
    ├── trading_preferences.py # 交易偏好 → 注入大模型 system
    ├── agent/
    │   ├── state.py        # Agent 运行态（已拉取的价格/资金流等）
    │   ├── planner.py      # 下一步动作规划（不调用 LLM，可替换策略）
    │   └── loop.py         # Agent Loop：Plan → Tool / Synthesize
    ├── tools/
    │   ├── mock_data.py    # Mock 行情与资金流
    │   ├── akshare_daily.py # 日线收盘价/涨跌幅
    │   ├── akshare_meta.py  # 名称、ETF/股票类型、行业、板块、概念摘要
    │   ├── akshare_flow.py  # 主力/散户侧净流入（万元）
    │   └── registry.py     # 工具注册（可按 Settings 选数据源）
    ├── memory/
    │   └── store.py        # 自选列表 + 最近一次分析记录
    ├── analysis/
    │   ├── rules.py        # 规则层信号与粗决策
    │   └── synthesizer.py  # 规则 + LLM 结构化输出
    ├── llm/
    │   └── client.py       # Mock / OpenAI 兼容（ChatGPT、DeepSeek 等）
    └── web/
        └── app.py          # FastAPI：/api/watchlist、/api/analyze 等
```

## 环境要求

- Python 3.10+

## 安装与运行

在项目根目录：

```bash
pip install -e .
python main.py
```

### AKShare 日线行情（可选）

安装 AKShare 后，在 `use_akshare_daily`（默认开启，环境变量 `ETF_USE_AKSHARE`）为真时：
- **价格**：最近一根日线收盘与涨跌幅（ETF `fund_etf_hist_em` / 股票 `stock_zh_a_hist`）。日线回溯自然日数由配置 **`akshare_daily_lookback_days`**（默认 120，可用环境变量 **`ETF_AKSHARE_LOOKBACK_DAYS`** 覆盖，范围 5～3650），越大请求越慢。档案字段：ETF 用 `fund_etf_spot_em`（全表，进程内缓存约 **15 分钟**）；股票 **不再**调用极慢的 `stock_zh_a_spot_em`，仅用单标的 **`stock_individual_info_em`**。
- **资金流**：`stock_individual_fund_flow` 最新一日，主力与中单+小单净流入（万元）。ETF 代码若东财无资金流接口会回退 Mock。

任一步失败则自动回退 Mock。

```bash
pip install -e ".[akshare]"
# 或: pip install akshare
```

关闭 AKShare、仅用 Mock：`ETF_USE_AKSHARE=0`。

### Web 自选与前端

安装 Web 依赖后启动（浏览器打开 <http://127.0.0.1:8000/>）：

```bash
pip install -e ".[web]"
python run_web.py
```

- 页面：管理自选（代码、可选名称、类型）、对单标的触发分析、查看结构化结果与步进轨迹。
- HTTP API：`GET/POST/PATCH/DELETE /api/watchlist`、`PUT /api/watchlist/reorder`、`POST /api/analyze/{code}`、`GET /api/last-analysis`，详见 <http://127.0.0.1:8000/docs>。

若不安装为包，可临时设置 `PYTHONPATH` 指向项目根目录后再执行 `python main.py` / `python run_web.py`。

Demo 会向自选加入 `510300`，跑一轮 Agent（先价格工具、再资金流工具、再合成），并在终端打印结构化决策与步进说明；数据写入 `data/watchlist_memory.json`。

## 配置文件与环境变量

### 配置文件（推荐）

**运行时只会加载 `etf_config.yaml`（或同目录下的 `etf_config.yml` / `etf_config.json`），不会读取 `etf_config.example.yaml`。** 若这些文件都不存在，则仅使用代码默认值 + 环境变量。

1. 将 **`etf_config.example.yaml`** 复制为 **`etf_config.yaml`**（与 `main.py` 同目录），再按需修改。
2. `etf_config.yaml` 已在 `.gitignore` 中，避免把密钥提交进 Git。
3. 也可用 **`etf_config.json`**（字段名相同）。
4. 自定义路径：设置 **`ETF_CONFIG_PATH`** 或 **`ETF_CONFIG_FILE`** 指向你的配置文件。

**加载优先级（后者覆盖前者）**：代码默认值 → 上述配置文件 → 环境变量。

### 环境变量在哪里设？

- **Windows（当前终端会话，PowerShell）**：`$env:OPENAI_API_KEY = "sk-..."`  
- **Windows（用户级持久）**：系统设置 → 环境变量，或 `setx OPENAI_API_KEY "sk-..."`（新开终端生效）。  
- **`.env`**：复制 `.env.example` 为 **`.env`**（已在 `.gitignore`）。安装 `pip install -e ".[llm]"` 后，程序启动时会自动加载 `.env`（不覆盖已存在的环境变量）。  
- **VS Code / Cursor**：可在 **Run/Debug 的 env** 中配置密钥，避免写进仓库。  
- **Linux / macOS**：`export OPENAI_API_KEY=sk-...`，或写入 `~/.bashrc`、`~/.zshrc`。

### 环境变量一览

| 变量 | 说明 |
|------|------|
| `ETF_CONFIG_PATH` / `ETF_CONFIG_FILE` | 配置文件绝对或相对路径 |
| `ETF_API_KEY` | API 密钥（与下列变量择一即可，按顺序优先匹配非空值） |
| `OPENAI_API_KEY` / `ETF_LLM_API_KEY` / `LLM_API_KEY` / `DEEPSEEK_API_KEY` | 同上，兼容旧习惯命名 |
| `ETF_MODEL_NAME` | 覆盖配置中的 `model_name`（优先级高于 `ETF_OPENAI_MODEL`、`ETF_LLM_MODEL`） |
| `ETF_MODEL_URL` | 覆盖 `model_url`（优先级高于 `ETF_LLM_BASE_URL`） |
| `ETF_LLM_BASE_URL` | 同 `ETF_MODEL_URL` |
| `ETF_OPENAI_MODEL` / `ETF_LLM_MODEL` | 覆盖 `model_name` |
| `ETF_USE_MOCK_LLM` | `0` / `false` / `no`：关闭 Mock，使用真实大模型（需已配置 Key 且 `pip install -e ".[llm]"`） |
| `ETF_USE_AKSHARE` | `0` / `false` / `no`：不请求 AKShare，价格/档案/资金流均回退 Mock |
| `ETF_AKSHARE_LOOKBACK_DAYS` | 覆盖 `akshare_daily_lookback_days`（整数，5～3650） |
| `ETF_DATA_DIR` | 覆盖 `data_dir` |
| `ETF_MEMORY_FILE` | 覆盖 `memory_file` |
| `ETF_MAX_AGENT_STEPS` | 覆盖 `max_agent_steps`（整数） |

安装大模型依赖（OpenAI SDK + 可选 `python-dotenv`）：

```bash
pip install -e ".[llm]"
```

### 大模型与密钥安全

配置文件里大模型 **统一三项**：`api_key`、`model_name`、`model_url`（任意 OpenAI 兼容服务同一写法）。

- **不要把 API Key 提交到 Git**：`etf_config.yaml`、`.env`、`*secrets.yaml` 已在 `.gitignore`；仓库内只保留 **`etf_config.example.yaml`** / **`.env.example`**。
- **推荐**：密钥只放在 **环境变量** 或 **`.env`**，yaml 里 `api_key: null`，并设 `use_mock_llm: false`。
- **`model_url` 留空**：SDK 使用默认地址（通常仅适用于 OpenAI 官方）；**DeepSeek 等第三方必须填写**，例如 `https://api.deepseek.com/v1`，`model_name` 如 `deepseek-chat`。
- 旧版 yaml 中的 `openai_api_key` / `openai_model` / `llm_base_url` 仍会自动映射到上述字段，无需立刻改文件。

启用真实模型须 **同时**满足：`use_mock_llm` 为 `false`（或 `ETF_USE_MOCK_LLM=0`）且能解析到非空 `api_key`。

### 交易偏好（强制约束大模型）

在 **`etf_config.yaml`** 的 `trading_preferences` 中配置（结构可参考仓库里的模板 `etf_config.example.yaml`，但程序只读 `etf_config.yaml`）：风险承受、投资周期、单标的仓位上限、规避行业/关键词、关注主题、以及 **`must_follow_text`** 自由文本。加载后写入大模型 **system**，在「解释」与「结构化 JSON 决策」两步均生效；模型须遵守，若与行情冲突应在 `reason` 中说明并倾向更保守的 `decision`。

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

- **真实数据**：日线已接 `akshare_daily.py`；其它周期或资金流可仿照 `mock_data` 签名在 `build_default_registry(settings)` 中替换注册。
- **新指标**：在 `RuleEngine.evaluate` 中增加字段，并在 `MemoryStore.AnalysisRecord` 中持久化需要的部分。
- **更强 Planner**：将 `plan_next_step` 替换为基于 LLM 的规划器，仍通过 `ToolRegistry.call` 执行工具，保持 Loop 形状不变。

## 许可证

按你的需要自行补充（当前仓库未默认指定）。
