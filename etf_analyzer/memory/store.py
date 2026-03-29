"""自选列表与最近一次分析结果的持久化（JSON）。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class WatchlistItem:
    """自选标的：支持股票 / ETF 等，便于前端展示与扩展。"""

    code: str
    name: str = ""
    asset_type: str = "auto"  # auto | stock | etf

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WatchlistItem":
        return cls(
            code=str(d["code"]).strip().upper(),
            name=str(d.get("name") or "").strip(),
            asset_type=str(d.get("asset_type") or "auto").strip() or "auto",
        )


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
    Memory：自选（可配置名称/类型）+ 最近一次分析。
    兼容旧版仅含 watchlist: ["510300"] 的 JSON。
    """

    def __init__(self, file_path: str | Path) -> None:
        self._path = Path(file_path)
        self._items: list[WatchlistItem] = []
        self._last_analysis: AnalysisRecord | None = None
        self._load()

    @property
    def watchlist(self) -> list[str]:
        """仅代码列表，兼容旧调用。"""
        return [i.code for i in self._items]

    @property
    def watchlist_items(self) -> list[WatchlistItem]:
        return list(self._items)

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

        raw_items = data.get("watchlist_items")
        migrated_from_legacy = False
        if raw_items and isinstance(raw_items, list):
            self._items = []
            for x in raw_items:
                if isinstance(x, dict) and x.get("code"):
                    self._items.append(WatchlistItem.from_dict(x))
        else:
            legacy = data.get("watchlist") or []
            self._items = []
            if legacy and isinstance(legacy[0], str):
                migrated_from_legacy = True
                self._items = [WatchlistItem(code=str(c).strip().upper()) for c in legacy if c]
            elif legacy and isinstance(legacy[0], dict):
                migrated_from_legacy = True
                for x in legacy:
                    if isinstance(x, dict) and x.get("code"):
                        self._items.append(WatchlistItem.from_dict(x))

        la = data.get("last_analysis")
        if la:
            self._last_analysis = AnalysisRecord.from_dict(la)

        if migrated_from_legacy:
            self.save()

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "watchlist_items": [i.to_dict() for i in self._items],
        }
        if self._last_analysis:
            payload["last_analysis"] = self._last_analysis.to_dict()
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def add_watchlist_item(
        self,
        code: str,
        *,
        name: str = "",
        asset_type: str = "auto",
    ) -> WatchlistItem:
        code = code.strip().upper()
        if not code:
            raise ValueError("empty code")
        name = name.strip()
        for idx, it in enumerate(self._items):
            if it.code == code:
                new_name = name or it.name
                new_type = asset_type if asset_type != "auto" else it.asset_type
                self._items[idx] = WatchlistItem(
                    code=code, name=new_name, asset_type=new_type
                )
                self.save()
                return self._items[idx]
        self._items.append(
            WatchlistItem(code=code, name=name, asset_type=asset_type)
        )
        self.save()
        return self._items[-1]

    def update_watchlist_item(
        self,
        code: str,
        *,
        name: str | None = None,
        asset_type: str | None = None,
    ) -> WatchlistItem | None:
        code = code.strip().upper()
        for idx, it in enumerate(self._items):
            if it.code != code:
                continue
            new_name = name.strip() if name is not None else it.name
            if asset_type is not None:
                new_type = (asset_type.strip() or it.asset_type) or "auto"
            else:
                new_type = it.asset_type
            self._items[idx] = WatchlistItem(
                code=code, name=new_name, asset_type=new_type
            )
            self.save()
            return self._items[idx]
        return None

    def remove_watchlist_item(self, code: str) -> bool:
        code = code.strip().upper()
        before = len(self._items)
        self._items = [i for i in self._items if i.code != code]
        if len(self._items) < before:
            self.save()
            return True
        return False

    def reorder_watchlist(self, codes: list[str]) -> None:
        """按给定代码顺序重排；未出现的条目保留在末尾（保持原相对顺序）。"""
        order = [c.strip().upper() for c in codes if c.strip()]
        index_map = {c: i for i, c in enumerate(order)}
        tail = [i for i in self._items if i.code not in index_map]
        head = sorted(
            [i for i in self._items if i.code in index_map],
            key=lambda x: index_map[x.code],
        )
        self._items = head + tail
        self.save()

    def add_etf(self, code: str) -> None:
        self.add_watchlist_item(code)

    def remove_etf(self, code: str) -> None:
        self.remove_watchlist_item(code)

    def set_last_analysis(self, record: AnalysisRecord) -> None:
        self._last_analysis = record
        self.save()

    def clear_last_analysis(self) -> None:
        self._last_analysis = None
        self.save()
