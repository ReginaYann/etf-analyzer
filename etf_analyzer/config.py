"""项目级配置：etf_config.yaml / JSON + 环境变量覆盖；密钥勿入库。"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any

from .trading_preferences import TradingPreferences

# 程序只会在仓库根目录查找这些文件名（不会读取 etf_config.example.yaml）
CONFIG_FILENAMES = ("etf_config.yaml", "etf_config.yml", "etf_config.json")


def _repo_root() -> Path:
    """仓库根目录（含 main.py、etf_config.yaml 的目录）。"""
    return Path(__file__).resolve().parent.parent


def _maybe_load_dotenv() -> None:
    """若存在 .env 且已安装 python-dotenv，则加载（.env 应在 .gitignore 中）。"""
    env_path = _repo_root() / ".env"
    if not env_path.is_file():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(env_path, override=False)


def resolve_config_path() -> Path | None:
    """
    解析要加载的配置文件路径。

    未设置 ETF_CONFIG_PATH / ETF_CONFIG_FILE 时，**仅**在仓库根目录依次查找
    ``etf_config.yaml``、``etf_config.yml``、``etf_config.json``。
    **不会**读取 ``etf_config.example.yaml``（该文件仅供复制为模板）。

    若显式设置了 ETF_CONFIG_PATH / ETF_CONFIG_FILE，则使用你指定的任意路径。
    """
    for key in ("ETF_CONFIG_PATH", "ETF_CONFIG_FILE"):
        raw = os.environ.get(key)
        if raw:
            p = Path(raw).expanduser()
            if p.is_file():
                return p.resolve()
            return None

    root = _repo_root()
    for name in CONFIG_FILENAMES:
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


def _normalize_raw_config_keys(raw: dict[str, Any]) -> dict[str, Any]:
    """统一为 api_key / model_name / model_url；兼容旧字段 openai_*、llm_*。"""
    r = dict(raw)
    if "api_key" not in r and "openai_api_key" in r:
        r["api_key"] = r.get("openai_api_key")
    if "model_name" not in r:
        if "openai_model" in r:
            r["model_name"] = r.get("openai_model")
        elif "llm_model" in r:
            r["model_name"] = r.get("llm_model")
    if "model_url" not in r and "llm_base_url" in r:
        r["model_url"] = r.get("llm_base_url")
    return r


def _parse_file_overrides(raw: dict[str, Any]) -> dict[str, Any]:
    skip = {"trading_preferences"}
    allowed = {f.name for f in fields(Settings)} - skip
    out: dict[str, Any] = {}
    for key, val in raw.items():
        if key in skip:
            continue
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
        elif key == "akshare_daily_lookback_days":
            try:
                n = int(val)
            except (TypeError, ValueError):
                continue
            out[key] = max(5, min(n, 3650))
        elif key == "api_key":
            if val is None or val == "":
                out[key] = None
            else:
                out[key] = str(val).strip() or None
        elif key == "model_url":
            if val is None or str(val).strip() == "":
                out[key] = None
            else:
                out[key] = str(val).strip().rstrip("/")
        elif key in ("data_dir", "memory_file", "model_name"):
            if val is None:
                continue
            st = str(val).strip()
            if st:
                out[key] = st
        else:
            out[key] = val
    return out


def _apply_env_overrides(s: Settings) -> Settings:
    """环境变量覆盖当前 Settings（仅处理已设置的变量）。密钥优先用环境变量，避免写入 yaml。"""

    # API Key：按顺序取「已设置且非空」的环境变量（推荐密钥只放环境变量 / .env）
    for env_key in (
        "ETF_API_KEY",
        "OPENAI_API_KEY",
        "ETF_LLM_API_KEY",
        "LLM_API_KEY",
        "DEEPSEEK_API_KEY",
    ):
        if env_key not in os.environ:
            continue
        raw = (os.environ.get(env_key) or "").strip()
        if raw:
            s = replace(s, api_key=raw)
            break

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
        s = replace(s, model_name=v)
    if (v := os.environ.get("ETF_LLM_MODEL", "").strip()):
        s = replace(s, model_name=v)
    if (v := os.environ.get("ETF_MODEL_NAME", "").strip()):
        s = replace(s, model_name=v)
    if (v := os.environ.get("ETF_LLM_BASE_URL", "").strip()):
        s = replace(s, model_url=v.rstrip("/"))
    if (v := os.environ.get("ETF_MODEL_URL", "").strip()):
        s = replace(s, model_url=v.rstrip("/"))
    if "ETF_MAX_AGENT_STEPS" in os.environ:
        s = replace(s, max_agent_steps=int(os.environ["ETF_MAX_AGENT_STEPS"]))
    if "ETF_AKSHARE_LOOKBACK_DAYS" in os.environ:
        try:
            n = int(os.environ["ETF_AKSHARE_LOOKBACK_DAYS"])
            s = replace(s, akshare_daily_lookback_days=max(5, min(n, 3650)))
        except ValueError:
            pass

    return s


@dataclass(frozen=True)
class Settings:
    """运行时可注入，便于测试与扩展。

    use_akshare_daily：为 True 时优先用 AKShare 拉日线价格、证券档案与资金流向（失败回退 Mock）。
    api_key / model_name / model_url：任意 OpenAI Chat Completions 兼容服务；密钥勿提交仓库。
    model_url 为空时由 SDK 使用默认官方地址（通常仅适用于 OpenAI）；其它厂商请填写完整 Base URL（一般含 /v1）。
    """

    data_dir: str = "data"
    memory_file: str = "watchlist_memory.json"
    api_key: str | None = None
    model_name: str = "gpt-4o-mini"
    model_url: str | None = None
    use_mock_llm: bool = True
    max_agent_steps: int = 12
    use_akshare_daily: bool = True
    # AKShare 日线请求回溯自然日数（5～3650），越大越慢；建议 60～250
    akshare_daily_lookback_days: int = 120
    trading_preferences: TradingPreferences = field(default_factory=TradingPreferences)

    @classmethod
    def from_env(cls) -> Settings:
        """仅环境变量（不含配置文件），供测试或特殊场景。"""
        _maybe_load_dotenv()
        return _apply_env_overrides(Settings())


TRADING_PREFERENCES_JSON = "trading_preferences.json"


def merge_trading_preferences_overlay(s: Settings, overlay_path: Path) -> Settings:
    """将 data/trading_preferences.json 覆盖到当前 Settings（网页端保存的偏好）。"""
    if not overlay_path.is_file():
        return s
    try:
        raw = json.loads(overlay_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return s
    if not isinstance(raw, dict):
        return s
    base = asdict(s.trading_preferences)
    merged = {**base, **raw}
    tp = TradingPreferences.from_dict(merged)
    return replace(s, trading_preferences=tp)


def load_effective_settings(base: Settings | None = None) -> Settings:
    """default_settings 结果再合并 data 目录下的 trading_preferences.json。"""
    s = base if base is not None else default_settings()
    root = _repo_root()
    overlay = root / s.data_dir / TRADING_PREFERENCES_JSON
    return merge_trading_preferences_overlay(s, overlay)


def default_settings() -> Settings:
    """
    加载顺序：.env（可选 dotenv）→ dataclass 默认值 → etf_config.yaml/json → 环境变量。

    若环境变量中设置 ETF_USE_MOCK_LLM=0/false 且已配置 API Key，则关闭 Mock LLM。
    """
    _maybe_load_dotenv()
    s = Settings()
    path = resolve_config_path()
    if path is not None:
        raw = _normalize_raw_config_keys(_load_config_file(path))
        tp = TradingPreferences.from_dict(
            raw["trading_preferences"]
            if isinstance(raw.get("trading_preferences"), dict)
            else {}
        )
        overrides = _parse_file_overrides(raw)
        if overrides:
            s = replace(s, **overrides)
        s = replace(s, trading_preferences=tp)  # 每次读到配置文件都更新偏好
    s = _apply_env_overrides(s)
    if s.api_key and os.environ.get("ETF_USE_MOCK_LLM", "").lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        s = replace(s, use_mock_llm=False)
    return s
