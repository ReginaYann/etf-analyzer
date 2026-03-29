"""项目级配置：后续可接入真实 API / OpenAI。"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """运行时可注入，便于测试与扩展。"""

    data_dir: str = "data"
    memory_file: str = "watchlist_memory.json"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    use_mock_llm: bool = True
    max_agent_steps: int = 12

    @classmethod
    def from_env(cls) -> "Settings":
        key = os.environ.get("OPENAI_API_KEY")
        use_mock = os.environ.get("ETF_USE_MOCK_LLM", "1").lower() in ("1", "true", "yes")
        return cls(
            openai_api_key=key,
            use_mock_llm=use_mock if not key else use_mock,
        )


def default_settings() -> Settings:
    s = Settings.from_env()
    if s.openai_api_key and os.environ.get("ETF_USE_MOCK_LLM", "").lower() in ("0", "false", "no"):
        from dataclasses import replace

        return replace(s, use_mock_llm=False)
    return s
