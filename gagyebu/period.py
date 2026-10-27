"""대시보드·거래 내역의 기간 선택(월·분기·연·직접 지정)과 비교 기간."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Period:
    mode: str  # month | quarter | year | custom
    value: str  # month: YYYY-MM, quarter: YYYY-Qn, year: YYYY, custom: ""
    start: str
    end: str
    label: str
    prev_start: str
    prev_end: str
    prev_label: str

    @property
    def months(self) -> float:
        """기간에 포함된 개월 수(예산 비교용). 한 달 단위가 아니면 일수/30 으로 근사한다."""
        return {"month": 1, "quarter": 3, "year": 12}.get(self.mode) or (_days_between(self.start, self.end) + 1) / 30


def today_in_seoul(now: datetime | None = None) -> str:
    now = now or datetime.now(ZoneInfo("UTC"))
    return now.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


def month_of(d: str) -> str:
    return d[:7]


def add_months(ym: str, delta: int) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    total = y * 12 + (m - 1) + delta
    return f"{total // 12}-{total % 12 + 1:02d}"


def month_range(ym: str) -> tuple[str, str]:
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y}-{m:02d}-01", f"{y}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"


def month_label(ym: str) -> str:
    return f"{int(ym[:4])}년 {int(ym[5:7])}월"


def _days_between(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def month_period(ym: str) -> Period:
    prev = add_months(ym, -1)
    return Period("month", ym, *month_range(ym), month_label(ym), *month_range(prev), month_label(prev))


def quarter_period(y: int, q: int) -> Period:
    def rng(yy, qq):
        return f"{yy}-{qq * 3 - 2:02d}-01", f"{yy}-{qq * 3:02d}-{calendar.monthrange(yy, qq * 3)[1]:02d}"

    py, pq = (y - 1, 4) if q == 1 else (y, q - 1)
    return Period("quarter", f"{y}-Q{q}", *rng(y, q), f"{y}년 {q}분기", *rng(py, pq), f"{py}년 {pq}분기")


def year_period(y: int) -> Period:
    return Period("year", str(y), f"{y}-01-01", f"{y}-12-31", f"{y}년", f"{y - 1}-01-01", f"{y - 1}-12-31", f"{y - 1}년")


def custom_period(start: str, end: str) -> Period:
    if start > end:
        start, end = end, start
    days = _days_between(start, end) + 1
    prev_end = (date.fromisoformat(start) - timedelta(days=1)).isoformat()
    prev_start = (date.fromisoformat(prev_end) - timedelta(days=days - 1)).isoformat()
    return Period("custom", "", start, end, f"{start} ~ {end}", prev_start, prev_end, f"직전 {days}일")
