"""证券简称、行业、板块等元数据的磁盘缓存（仅手动刷新时强制重拉）。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _normalize_code(raw: str) -> str:
    s = "".join(c for c in (raw or "").strip().upper() if c.isalnum())
    if s.isdigit():
        return s.zfill(6)[-6:]
    return s


class SymbolMetaCache:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.is_file():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, dict):
            return
        out: dict[str, dict[str, Any]] = {}
        for k, v in raw.items():
            if isinstance(v, dict):
                c = _normalize_code(str(k))
                if c:
                    out[c] = v
        self._data = out

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self._path)

    def get(self, code: str) -> dict[str, Any] | None:
        c = _normalize_code(code)
        row = self._data.get(c)
        return dict(row) if row is not None else None

    def set_from_profile(self, code: str, profile: dict[str, Any]) -> None:
        c = _normalize_code(code)
        blob: dict[str, Any] = {
            "code": c,
            "name": str(profile.get("name") or ""),
            "asset_type": str(profile.get("asset_type") or "unknown"),
            "industry": str(profile.get("industry") or ""),
            "sector": str(profile.get("sector") or ""),
            "concept": str(profile.get("concept") or ""),
            "listing_board": str(profile.get("listing_board") or ""),
            "fund_type_detail": str(profile.get("fund_type_detail") or ""),
            "source": str(profile.get("source") or "akshare"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._data[c] = blob
        self.save()
