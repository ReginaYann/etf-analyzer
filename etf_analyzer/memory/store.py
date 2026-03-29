"""自选列表与最近一次分析结果的持久化（JSON）。"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AnalysisRecord:
    """单次分析的结构化结果，便于扩展字段。"""

    etf_code: str
    decision: str  # buy | sell | hold
    confidence: float
    reason: str
    rule_signals: dict[str, Any] = field(default_factory=dict)
    raw_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AnalysisRecord":
        return cls(
            etf_code=d["etf_code"],
            decision=d["decision"],
            confidence=float(d["confidence"]),
            reason=d["reason"],
            rule_signals=dict(d.get("rule_signals") or {}),
            raw_context=dict(d.get("raw_context") or {}),
        )


class MemoryStore:
    """
    简单 Memory：自选 ETF + 最近一次分析。
    未来可拆成 UserProfile / AnalysisHistory 等多表结构。
    """

    def __init__(self, file_path: str | Path) -> None:
        self._path = Path(file_path)
        self._watchlist: list[str] = []
        self._last_analysis: AnalysisRecord | None = None
        self._load()

    @property
    def watchlist(self) -> list[str]:
        return list(self._watchlist)

    @property
    def last_analysis(self) -> AnalysisRecord | None:
        return self._last_analysis

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return
        self._watchlist = list(data.get("watchlist") or [])
        la = data.get("last_analysis")
        if la:
            self._last_analysis = AnalysisRecord.from_dict(la)

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {"watchlist": self._watchlist}
        if self._last_analysis:
            payload["last_analysis"] = self._last_analysis.to_dict()
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def add_etf(self, code: str) -> None:
        code = code.strip().upper()
        if not code:
            return
        if code not in self._watchlist:
            self._watchlist.append(code)
        self.save()

    def remove_etf(self, code: str) -> None:
        code = code.strip().upper()
        self._watchlist = [c for c in self._watchlist if c != code]
        self.save()

    def set_last_analysis(self, record: AnalysisRecord) -> None:
        self._last_analysis = record
        self.save()

    def clear_last_analysis(self) -> None:
        self._last_analysis = None
        self.save()
