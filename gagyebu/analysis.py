"""소비패턴 분석. 모두 순수 함수이며 거래(dict: id, date, time, merchant, amount, category_id) 목록을 받는다."""

from __future__ import annotations

from datetime import date
from statistics import median

from .classify import base_merchant_name, normalize_merchant
from .period import add_months, month_of

UNCATEGORIZED = "none"  # 미분류 거래의 항목 키
HIGHLIGHT_MIN_DIFF = 50_000
HIGHLIGHT_MIN_RATE = 0.2
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]


def cat_key(tx: dict) -> str:
    return tx.get("category_id") or UNCATEGORIZED


def last_months(end_ym: str, n: int) -> list[str]:
    """end_ym 을 포함한 최근 n 개월 (오래된 달부터)"""
    return [add_months(end_ym, i - n + 1) for i in range(n)]


def monthly_series(txs: list[dict], end_ym: str, n: int = 12, category_keys: list[str] = ()) -> list[dict]:
    """최근 n 개월 월별 순지출. 거래가 하나도 없는 달은 0 이 아니라 None(차트에서 빈 칸)이다."""
    months = last_months(end_ym, n)
    wanted = set(months)
    sums: dict[str, dict[str, int]] = {}
    for tx in txs:
        m = month_of(tx["date"])
        if m not in wanted:
            continue
        bucket = sums.setdefault(m, {})
        bucket["__total"] = bucket.get("__total", 0) + tx["amount"]
        bucket[cat_key(tx)] = bucket.get(cat_key(tx), 0) + tx["amount"]
    out = []
    for m in months:
        bucket = sums.get(m)
        out.append(
            {
                "month": m,
                "total": bucket.get("__total", 0) if bucket else None,
                "by_category": {k: (bucket.get(k, 0) if bucket else None) for k in category_keys},
            }
        )
    return out


def compare_months(txs: list[dict], current_ym: str) -> list[dict]:
    """항목별 이번 달/지난달/증감. 증감액 큰 순. 20% 이상 + 5만원 이상 늘어난 항목을 강조한다."""
    prev_ym = add_months(current_ym, -1)
    totals: dict[str, list[int]] = {}
    for tx in txs:
        m = month_of(tx["date"])
        if m not in (current_ym, prev_ym):
            continue
        t = totals.setdefault(cat_key(tx), [0, 0])
        t[0 if m == current_ym else 1] += tx["amount"]
    rows = []
    for key, (current, previous) in totals.items():
        diff = current - previous
        rate = diff / previous if previous > 0 else None
        highlight = diff >= HIGHLIGHT_MIN_DIFF and (rate is None or rate >= HIGHLIGHT_MIN_RATE)
        rows.append({"key": key, "current": current, "previous": previous, "diff": diff, "rate": rate, "highlight": highlight})
    return sorted(rows, key=lambda r: -r["diff"])


def weekday_hour_grid(txs: list[dict]) -> dict:
    """[요일 0=월][시 0~23] 지출액. 환불이 빈 칸을 음수로 만들지 않게 지출(양수)만 센다."""
    grid = [[0] * 24 for _ in range(7)]
    weekday_totals = [0] * 7
    timed = 0
    for tx in txs:
        if tx["amount"] <= 0:
            continue
        wd = date.fromisoformat(tx["date"]).weekday()  # 월=0
        weekday_totals[wd] += tx["amount"]
        if tx.get("time"):
            grid[wd][int(tx["time"][:2])] += tx["amount"]
            timed += 1
    return {"has_time": timed > 0, "timed_count": timed, "grid": grid, "weekday_totals": weekday_totals}


def detect_recurring(txs: list[dict], end_ym: str, min_months: int = 3) -> list[dict]:
    """같은 사용처가 3개월 이상 연속, 결제일 ±3일·금액 ±10% 안에서 반복되면 고정지출.

    end_ym 또는 그 전달까지 이어지고 있는(아직 끝나지 않은) 것만 돌려준다.
    """
    by_merchant: dict[str, list[dict]] = {}
    for tx in txs:
        if tx["amount"] <= 0 or month_of(tx["date"]) > end_ym:
            continue
        key = normalize_merchant(tx["merchant"])
        if key:
            by_merchant.setdefault(key, []).append(tx)

    result = []
    for key, lst in by_merchant.items():
        per_month: dict[str, dict] = {}
        for tx in sorted(lst, key=lambda t: t["date"]):
            per_month.setdefault(month_of(tx["date"]), tx)  # 달마다 첫 결제만
        last = max(per_month)
        if last not in (end_ym, add_months(end_ym, -1)):
            continue
        run = []
        m = last
        while m in per_month:
            run.insert(0, per_month[m])
            m = add_months(m, -1)
        if len(run) < min_months:
            continue
        day = median(int(t["date"][8:10]) for t in run)
        amount = median(t["amount"] for t in run)
        steady = []
        for t in reversed(run):
            if abs(int(t["date"][8:10]) - day) > 3 or abs(t["amount"] - amount) > amount * 0.1:
                break
            steady.insert(0, t)
        if len(steady) < min_months:
            continue
        latest = steady[-1]
        result.append(
            {
                "key": key,
                "name": base_merchant_name(latest["merchant"]),
                "category_id": latest.get("category_id"),
                "amount": latest["amount"],
                "day": int(day + 0.5),
                "months": [month_of(t["date"]) for t in steady],
            }
        )
    return sorted(result, key=lambda r: -r["amount"])


def find_anomalies(txs: list[dict], current_ym: str) -> dict:
    """- 거래: 그 항목의 최근 3개월(이번 달 제외) 건당 평균의 2배를 넘는 이번 달 거래 (과거 3건 이상일 때)
    - 항목: 이번 달 합계가 최근 3개월 월평균(거래가 있는 달 기준)의 2배를 넘는 항목
    """
    past_months = set(last_months(add_months(current_ym, -1), 3))
    past = [t for t in txs if t["amount"] > 0 and month_of(t["date"]) in past_months]
    current = [t for t in txs if month_of(t["date"]) == current_ym]
    months_with_data = {month_of(t["date"]) for t in past}

    per_tx: dict[str, list[int]] = {}
    per_month: dict[str, dict[str, int]] = {}
    for t in past:
        s = per_tx.setdefault(cat_key(t), [0, 0])
        s[0] += t["amount"]
        s[1] += 1
        pm = per_month.setdefault(cat_key(t), {})
        pm[month_of(t["date"])] = pm.get(month_of(t["date"]), 0) + t["amount"]

    transactions = []
    for tx in current:
        s = per_tx.get(cat_key(tx))
        if not s or s[1] < 3 or tx["amount"] <= 0:
            continue
        avg = s[0] / s[1]
        if tx["amount"] > avg * 2:
            transactions.append({"tx": tx, "average": avg, "ratio": tx["amount"] / avg})

    current_totals: dict[str, int] = {}
    for t in current:
        current_totals[cat_key(t)] = current_totals.get(cat_key(t), 0) + t["amount"]
    categories = []
    if months_with_data:
        for key, total in current_totals.items():
            months = per_month.get(key)
            if not months:
                continue
            avg = sum(months.values()) / len(months_with_data)
            if avg > 0 and total > avg * 2:
                categories.append({"key": key, "total": total, "average": avg, "ratio": total / avg})

    return {
        "transactions": sorted(transactions, key=lambda a: -a["ratio"]),
        "categories": sorted(categories, key=lambda a: -a["ratio"]),
    }


def won(n: float) -> str:
    return f"{int(round(n)):,}원"


def _pct(r: float) -> str:
    return f"{round(abs(r) * 100)}%"


def monthly_summary(month_label: str, current: int, previous: int | None, changes: list[dict], category_name, recurring_total: int) -> list[str]:
    """분석 결과로 3~4문장 요약을 만든다. 숫자는 모두 입력값에서 나온다."""
    s = []
    if previous is None or previous <= 0:
        s.append(f"{month_label} 총지출은 {won(current)}입니다.")
    else:
        diff = current - previous
        s.append(f"{month_label} 총지출은 {won(current)}으로 지난달보다 {won(abs(diff))}({_pct(diff / previous)}) {'늘었' if diff >= 0 else '줄었'}습니다.")
    tops = sorted((c for c in changes if c["current"] > 0), key=lambda c: -c["current"])
    if tops and current > 0:
        top = tops[0]
        s.append(f"가장 많이 쓴 항목은 {category_name(top['key'])}({won(top['current'])}, 전체의 {_pct(top['current'] / current)})입니다.")
    rise = next((c for c in changes if c["diff"] > 0 and c["previous"] > 0), None)
    if rise:
        s.append(f"{category_name(rise['key'])} 지출이 지난달보다 {won(rise['diff'])}({_pct(rise['rate'] or 0)}) 늘었습니다.")
    if recurring_total > 0:
        s.append(f"매달 나가는 고정지출은 약 {won(recurring_total)}입니다.")
    return s


def link_refunds(txs: list[dict]) -> dict[str, dict]:
    """취소·환불(음수) 거래를 같은 사용처·같은 금액의 이전 원 거래와 짝짓는다(목록 표시용).

    환불일 이전의 원 거래 중 가장 가까운 것을 고르고, 한 원 거래는 한 번만 짝지어진다.
    """
    links: dict[str, dict] = {}
    refunds = sorted((t for t in txs if t["amount"] < 0), key=lambda t: t["date"])
    originals = [t for t in txs if t["amount"] > 0]
    for refund in refunds:
        key = normalize_merchant(refund["merchant"])
        candidates = [
            o
            for o in originals
            if o["id"] not in links and o["amount"] == -refund["amount"] and o["date"] <= refund["date"] and normalize_merchant(o["merchant"]) == key
        ]
        if not candidates:
            continue
        original = max(candidates, key=lambda o: o["date"])
        links[original["id"]] = {"role": "original", "pair_id": refund["id"], "pair_date": refund["date"]}
        links[refund["id"]] = {"role": "refund", "pair_id": original["id"], "pair_date": original["date"]}
    return links
