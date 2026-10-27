"""기간·분석·환불 짝짓기·데이터 조작 테스트. Next.js 판 lib/analysis/analysis.test.ts 와 같은 기대값을 쓴다."""

from datetime import datetime, timezone
from itertools import count

import pytest

from gagyebu import store
from gagyebu.analysis import compare_months, detect_recurring, find_anomalies, link_refunds, monthly_series, monthly_summary, weekday_hour_grid
from gagyebu.period import custom_period, month_period, quarter_period, today_in_seoul, year_period

_seq = count(1)


def tx(d, merchant, amount, cat="food", t=None):
    return {"id": f"t{next(_seq)}", "date": d, "time": t, "merchant": merchant, "amount": amount, "category_id": cat}


def test_periods():
    p = month_period("2026-10")
    assert (p.start, p.end, p.label, p.prev_start, p.prev_end) == ("2026-10-01", "2026-10-31", "2026년 10월", "2026-09-01", "2026-09-30")
    assert (month_period("2026-01").prev_start, month_period("2026-01").prev_end) == ("2025-12-01", "2025-12-31")
    q = quarter_period(2026, 1)
    assert (q.start, q.end, q.prev_start, q.prev_end) == ("2026-01-01", "2026-03-31", "2025-10-01", "2025-12-31")
    assert (year_period(2024).start, year_period(2024).end) == ("2024-01-01", "2024-12-31")
    c = custom_period("2026-09-11", "2026-09-20")
    assert (c.prev_start, c.prev_end) == ("2026-09-01", "2026-09-10")
    assert today_in_seoul(datetime(2026, 10, 31, 16, tzinfo=timezone.utc)) == "2026-11-01"


def test_monthly_series_none_for_empty_months():
    s = monthly_series([tx("2026-07-03", "a", 1000), tx("2026-09-01", "b", 500, "cafe")], "2026-09", 3, ["food", "cafe"])
    assert [p["month"] for p in s] == ["2026-07", "2026-08", "2026-09"]
    assert [p["total"] for p in s] == [1000, None, 500]
    assert s[2]["by_category"] == {"food": 0, "cafe": 500}
    assert s[1]["by_category"] == {"food": None, "cafe": None}


def test_compare_months_sort_and_highlight():
    rows = compare_months(
        [
            tx("2026-08-10", "a", 200_000, "food"), tx("2026-09-10", "a", 260_000, "food"),
            tx("2026-08-10", "b", 1_000_000, "rent"), tx("2026-09-10", "b", 1_060_000, "rent"),
            tx("2026-09-11", "c", 70_000, "new"), tx("2026-08-11", "d", 30_000, "cafe"),
        ],
        "2026-09",
    )  # fmt: skip
    assert [(r["key"], r["diff"], r["highlight"]) for r in rows] == [("new", 70_000, True), ("food", 60_000, True), ("rent", 60_000, False), ("cafe", -30_000, False)]
    assert next(r for r in rows if r["key"] == "new")["rate"] is None


def test_weekday_hour_grid():
    g = weekday_hour_grid([tx("2026-09-07", "a", 1000, t="12:30:00"), tx("2026-09-13", "b", 500, t="23:59:00"), tx("2026-09-07", "c", -1000, t="12:00:00"), tx("2026-09-08", "d", 700)])
    assert g["has_time"] and g["grid"][0][12] == 1000 and g["grid"][6][23] == 500
    assert g["weekday_totals"][:2] == [1000, 700]
    assert not weekday_hour_grid([tx("2026-09-07", "a", 1000)])["has_time"]


def netflix(ym, day, amount=17000):
    return tx(f"{ym}-{day}", "NETFLIX.COM", amount, "sub")


def test_detect_recurring():
    r = detect_recurring([netflix("2026-07", "07"), netflix("2026-08", "08"), netflix("2026-09", "06", 17500)], "2026-09")
    assert len(r) == 1 and r[0]["amount"] == 17500 and r[0]["day"] == 7 and r[0]["months"] == ["2026-07", "2026-08", "2026-09"]
    assert detect_recurring([netflix("2026-08", "07"), netflix("2026-09", "07")], "2026-09") == []
    assert detect_recurring([netflix("2026-06", "07"), netflix("2026-07", "07"), netflix("2026-09", "07")], "2026-09") == []
    assert detect_recurring([netflix("2026-07", "07"), netflix("2026-08", "20"), netflix("2026-09", "07")], "2026-09") == []
    assert detect_recurring([netflix("2026-07", "07"), netflix("2026-08", "07", 30000), netflix("2026-09", "07")], "2026-09") == []
    assert detect_recurring([netflix("2026-05", "07"), netflix("2026-06", "07"), netflix("2026-07", "07")], "2026-09") == []


PAST = [tx(f"{m}-{d}", "식당", a) for m in ("2026-06", "2026-07", "2026-08") for d, a in (("05", 10_000), ("15", 12_000))]


def test_anomalies():
    res = find_anomalies(PAST + [tx("2026-09-10", "고급식당", 50_000), tx("2026-09-11", "식당", 11_000)], "2026-09")
    assert [a["tx"]["merchant"] for a in res["transactions"]] == ["고급식당"]
    assert round(res["transactions"][0]["average"]) == 11_000
    cats = find_anomalies(PAST + [tx("2026-09-10", "식당", 25_000), tx("2026-09-12", "식당", 25_000)], "2026-09")["categories"]
    assert len(cats) == 1 and cats[0]["key"] == "food" and cats[0]["total"] == 50_000 and cats[0]["average"] == 22_000
    assert find_anomalies([tx("2026-09-10", "식당", 500_000)], "2026-09") == {"transactions": [], "categories": []}


def test_monthly_summary():
    changes = compare_months([tx("2026-08-01", "a", 100_000), tx("2026-09-01", "a", 118_000), tx("2026-09-02", "b", 82_000, "cafe")], "2026-09")
    names = {"food": "식비", "cafe": "카페·간식"}
    assert monthly_summary("2026년 9월", 200_000, 100_000, changes, lambda k: names.get(k, k), 17_000) == [
        "2026년 9월 총지출은 200,000원으로 지난달보다 100,000원(100%) 늘었습니다.",
        "가장 많이 쓴 항목은 식비(118,000원, 전체의 59%)입니다.",
        "식비 지출이 지난달보다 18,000원(18%) 늘었습니다.",
        "매달 나가는 고정지출은 약 17,000원입니다.",
    ]


def test_link_refunds():
    a, b, c = tx("2026-09-05", "쿠팡", 45_000), tx("2026-09-06", "KCP_쿠팡", -45_000), tx("2026-09-07", "쿠팡", 45_000)
    links = link_refunds([a, b, c])
    assert links[a["id"]]["role"] == "original" and links[a["id"]]["pair_id"] == b["id"]
    assert links[b["id"]] == {"role": "refund", "pair_id": a["id"], "pair_date": "2026-09-05"}
    assert c["id"] not in links
    assert link_refunds([tx("2026-09-05", "쿠팡", 45_000), tx("2026-09-06", "쿠팡", -5_000)]) == {}


# 데이터 조작 ---------------------------------------------------------------------------


def test_store_rule_apply_category_delete_and_backup_roundtrip():
    data = store.new_store()
    ids = {c["name"]: c["id"] for c in data["categories"]}
    store.import_rows(data, "a.xlsx", None, [{"date": "2026-09-01", "time": None, "merchant": f"동네가게 {i}호점", "amount": 1000, "memo": None} for i in range(3)], lambda m: None)
    first = data["transactions"][0]
    store.set_category(data, {first["id"]}, ids["식비"], "manual")
    rule = store.upsert_rule(data, "동네가게", ids["쇼핑"])
    assert store.apply_rule(data, rule) == 2  # 수동 분류한 1건은 그대로
    assert first["category_id"] == ids["식비"]

    sub = store.add_category(data, "생필품", parent_id=ids["쇼핑"])
    store.set_category(data, {data["transactions"][1]["id"]}, sub["id"])
    with pytest.raises(store.StoreError):
        store.add_category(data, "생필품", parent_id=ids["쇼핑"])
    store.delete_category(data, ids["쇼핑"])  # 쇼핑 거래 → 기타, 하위 항목 거래 → 미분류, 규칙 삭제
    cats = [t["category_id"] for t in data["transactions"]]
    assert cats == [ids["식비"], None, ids["기타"]]
    assert data["rules"] == [] and all(c["name"] not in ("쇼핑", "생필품") for c in data["categories"])
    with pytest.raises(store.StoreError):
        store.delete_category(data, ids["기타"])

    restored = store.load_backup(store.dump_backup(data))
    assert restored["transactions"] == data["transactions"]
    with pytest.raises(store.StoreError):
        store.load_backup(b"not json")
    assert store.delete_batch(restored, restored["import_batches"][0]["id"]) == 3
