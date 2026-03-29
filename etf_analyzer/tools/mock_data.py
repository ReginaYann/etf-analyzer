"""
Mock 行情与资金流 — 后续可替换为 akshare / 东方财富 / 券商 API 等。
保持函数签名稳定，Agent 与 Registry 无需改动。
"""

from __future__ import annotations

import hashlib
import random
from typing import Any


def _seed_for(code: str) -> int:
    h = hashlib.md5(code.encode("utf-8")).hexdigest()
    return int(h[:8], 16)


def get_etf_price(etf_code: str) -> dict[str, Any]:
    """
    返回模拟价格与涨跌幅。
    真实实现可返回: last, prev_close, change_pct, volume 等。
    """
    code = (etf_code or "").strip().upper()
    rng = random.Random(_seed_for(code))
    base = 1.0 + (rng.random() * 4.0)
    last = round(base + rng.uniform(-0.15, 0.15), 3)
    change_pct = round(rng.uniform(-5.0, 5.0), 2)
    return {
        "etf_code": code,
        "last": last,
        "change_pct": change_pct,
        "currency": "CNY",
        "source": "mock",
    }


def get_etf_flow(etf_code: str) -> dict[str, Any]:
    """
    返回模拟资金流向（万元级），正数近似代表净流入。
    """
    code = (etf_code or "").strip().upper()
    rng = random.Random(_seed_for(code) + 7)
    main_net = round(rng.uniform(-8000, 8000), 0)
    retail_net = round(-main_net * 0.3 + rng.uniform(-500, 500), 0)
    return {
        "etf_code": code,
        "main_force_net_wan": main_net,
        "retail_net_wan": retail_net,
        "source": "mock",
    }
