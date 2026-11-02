"""API 用量統計（docs/data/usage.json），按月份累計。"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path


class Budget:
    def __init__(self, path: Path, today: date, limits: dict[str, int] | None = None,
                 per_run: dict[str, int] | None = None) -> None:
        self.path = path
        self.month = today.strftime("%Y-%m")
        self.limits = limits or {}
        self.per_run = per_run or {}
        self.run_counts: dict[str, int] = {}
        self.data: dict = {}
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
        self.data.setdefault("months", {})
        # 只保留最近 12 個月的統計
        for old in sorted(self.data["months"])[:-12]:
            del self.data["months"][old]

    def used(self, source: str) -> int:
        return int(self.data["months"].get(self.month, {}).get(source, 0))

    def can_call(self, source: str, cost: int = 1) -> bool:
        if source in self.limits and self.used(source) + cost > self.limits[source]:
            return False
        if source in self.per_run and self.run_counts.get(source, 0) + cost > self.per_run[source]:
            return False
        return True

    def record(self, source: str, cost: int = 1) -> None:
        month = self.data["months"].setdefault(self.month, {})
        month[source] = int(month.get(source, 0)) + cost
        self.run_counts[source] = self.run_counts.get(source, 0) + cost

    def save(self) -> None:
        self.data["limits"] = self.limits
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
