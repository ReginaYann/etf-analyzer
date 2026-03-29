"""项目级配置：etf_config.yaml / JSON + 环境变量覆盖。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    """仓库根目录（含 main.py、etf_config.yaml 的目录）。"""
    return Path(__file__).resolve().parent.parent


def resolve_config_path() -> Path | None:
    """
    配置文件路径：
    1) 环境变量 ETF_CONFIG_PATH 或 ETF_CONFIG_FILE（可指向 .yaml / .yml / .json）
    2) 仓库根目录下的 etf_config.yaml
    3) 仓库根目录下的 etf_config.json
    """
    for key in ("ETF_CONFIG_PATH", "ETF_CONFIG_FILE"):
        raw = os.environ.get(key)
        if raw:
            p = Path(raw).expanduser()
            if p.is_file():
                return p.resolve()
            return None

    root = _repo_root()
    for name in ("etf_config.yaml", "etf_config.yml", "etf_config.json"):
        cand = root / name
        if cand.is_file():
            return cand.resolve()
    return None


def _load_config_file(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")
    if suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as e:
            raise ImportError(
                "读取 YAML 配置需要安装 PyYAML：pip install pyyaml"
            ) from e
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as e:
            raise ValueError(f"YAML 解析失败 {path}: {e}") from e
    else:
        data = json.loads(text)
    return data if isinstance(data, dict) else {}


def _parse_file_overrides(raw: dict[str, Any]) -> dict[str, Any]:
    allowed = {f.name for f in fields(Settings)}
    out: dict[str, Any] = {}
    for key, val in raw.items():
        if key not in allowed:
            continue
        if key in ("use_mock_llm", "use_akshare_daily"):
            if isinstance(val, bool):
                out[key] = val
            elif isinstance(val, str):
                out[key] = val.strip().lower() in ("1", "true", "yes", "on")
            else:
                out[key] = bool(val)
        elif key == "max_agent_steps":
            out[key] = int(val)
        elif key == "openai_api_key":
            if val is None or val == "":
                out[key] = None
            else:
                out[key] = str(val).strip() or None
        elif key in ("data_dir", "memory_file", "openai_model"):
            if val is None:
                continue
            st = str(val).strip()
            if st:
                out[key] = st
        else:
            out[key] = val
    return out


def _apply_env_overrides(s: Settings) -> Settings:
    """环境变量覆盖当前 Settings（仅处理已设置的变量）。"""

    if "OPENAI_API_KEY" in os.environ:
        raw = os.environ.get("OPENAI_API_KEY") or ""
        s = replace(s, openai_api_key=raw.strip() or None)

    if "ETF_USE_MOCK_LLM" in os.environ:
        v = os.environ["ETF_USE_MOCK_LLM"].lower()
        s = replace(s, use_mock_llm=v in ("1", "true", "yes", "on"))

    if "ETF_USE_AKSHARE" in os.environ:
        v = os.environ["ETF_USE_AKSHARE"].lower()
        s = replace(s, use_akshare_daily=v not in ("0", "false", "no", "off"))

    if (v := os.environ.get("ETF_DATA_DIR", "").strip()):
        s = replace(s, data_dir=v)
    if (v := os.environ.get("ETF_MEMORY_FILE", "").strip()):
        s = replace(s, memory_file=v)
    if (v := os.environ.get("ETF_OPENAI_MODEL", "").strip()):
        s = replace(s, openai_model=v)
    if "ETF_MAX_AGENT_STEPS" in os.environ:
        s = replace(s, max_agent_steps=int(os.environ["ETF_MAX_AGENT_STEPS"]))

    return s


@dataclass(frozen=True)
class Settings:
    """运行时可注入，便于测试与扩展。

    use_akshare_daily：为 True 时优先用 AKShare 拉日线价格、证券档案与资金流向（失败回退 Mock）。
    """

    data_dir: str = "data"
    memory_file: str = "watchlist_memory.json"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    use_mock_llm: bool = True
    max_agent_steps: int = 12
    use_akshare_daily: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        """仅环境变量（不含配置文件），供测试或特殊场景。"""
        return _apply_env_overrides(Settings())


def default_settings() -> Settings:
    """
    加载顺序：dataclass 默认值 → etf_config.yaml/json → 环境变量。
    若存在 OPENAI_API_KEY 且 ETF_USE_MOCK_LLM=0，则关闭 Mock LLM（与原先逻辑一致）。
    """
    s = Settings()
    path = resolve_config_path()
    if path is not None:
        raw = _load_config_file(path)
        overrides = _parse_file_overrides(raw)
        if overrides:
            s = replace(s, **overrides)
    s = _apply_env_overrides(s)
    if s.openai_api_key and os.environ.get("ETF_USE_MOCK_LLM", "").lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        s = replace(s, use_mock_llm=False)
    return s
