"""엑셀 읽기·감지·정규화 테스트. Next.js 판 lib/import/*.test.ts 와 같은 기대값을 쓴다."""

import io
import time
from pathlib import Path

import pytest
from openpyxl import Workbook

from gagyebu.importer import (
    RowResult,
    build_rows,
    find_header_row,
    find_sensitive_columns,
    from_preset_mapping,
    guess_mapping,
    is_missing,
    mark_duplicates,
    parse_amount,
    parse_date,
    parse_time,
    read_workbook,
    to_preset_mapping,
)

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def load(name):
    return read_workbook((SAMPLES / name).read_bytes(), name)


def analyze(table):
    """앱과 같은 순서: 헤더 감지 → 민감 열 제외 → 열 추측 → 행 변환"""
    hi = find_header_row(table.rows)
    header = table.rows[hi]
    sensitive = find_sensitive_columns(header, table.rows[hi + 1 :])
    mapping = guess_mapping(header, sensitive)
    results, skipped = build_rows(table, hi, mapping)
    names = {f: str(header[c]) for f, c in mapping.items()}
    ok = [r for r in results if r.status == "ok"]
    errors = [r for r in results if r.status == "error"]
    return dict(hi=hi, header=header, sensitive=sensitive, names=names, ok=ok, errors=errors, skipped=skipped)


# 정규화 -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("2026.10.01", "2026-10-01"), ("2026-10-01", "2026-10-01"), ("2026/10/1", "2026-10-01"), ("2026. 10. 01.", "2026-10-01"),
        ("2026년 10월 1일", "2026-10-01"), ("20261001", "2026-10-01"), ("26/10/01", "2026-10-01"), ("26.10.01", "2026-10-01"),
    ],
)  # fmt: skip
def test_parse_date_formats(text, expected):
    assert parse_date(text)[0] == expected


def test_parse_date_excel_serial_and_time():
    assert parse_date(46296) == ("2026-10-01", None)
    assert parse_date(46296.5) == ("2026-10-01", "12:00:00")
    assert parse_date("2026.09.03 08:12:45") == ("2026-09-03", "08:12:45")
    assert parse_date("2026-09-03 오후 2:05") == ("2026-09-03", "14:05:00")


@pytest.mark.parametrize("text", ["2026.13.45", "2026-02-30", "확인중", "", "1234"])
def test_parse_date_invalid(text):
    assert parse_date(text) is None


def test_parse_date_ignores_amount_like_numbers():
    assert parse_date(5600) is None


@pytest.mark.parametrize(
    "text,expected",
    [("14:05", "14:05:00"), ("14:05:30", "14:05:30"), ("140530", "14:05:30"), ("오전 12:10", "00:10:00"), ("오후 12:10", "12:10:00"), ("PM 3:00", "15:00:00")],
)
def test_parse_time(text, expected):
    assert parse_time(text) == expected


def test_parse_time_fraction_and_invalid():
    assert parse_time(0.5) == "12:00:00"
    assert parse_time(46296.75) == "18:00:00"
    assert parse_time("25:00") is None
    assert parse_time(None) is None


@pytest.mark.parametrize(
    "value,expected",
    [
        (12000, 12000), (12000.4, 12000), ("12,000", 12000), ("12,000원", 12000), ("₩12,000", 12000),
        ("-3,500", -3500), ("(3,500)", -3500), ("(3,500원)", -3500), ("△3,500", -3500), (" 1 200 ", 1200),
    ],
)  # fmt: skip
def test_parse_amount(value, expected):
    assert parse_amount(value) == expected


def test_parse_amount_missing_and_invalid():
    assert is_missing(parse_amount(None)) and is_missing(parse_amount("")) and is_missing(parse_amount("-"))
    assert parse_amount("확인중") is None
    assert parse_amount("12,000달러") is None


# 샘플 파일 ---------------------------------------------------------------------------


def test_card_a_header_title_rows_and_summary():
    a = analyze(load("card-a.xlsx"))
    assert a["hi"] == 3
    assert a["names"] == {"date": "이용일자", "merchant": "가맹점명", "amount": "이용금액"}
    assert [a["header"][c] for c in a["sensitive"]] == ["이용카드"]
    assert len(a["ok"]) == 13 and len(a["errors"]) == 0 and a["skipped"] == 1
    assert a["ok"][0].tx == {"date": "2026-09-01", "time": None, "merchant": "스타벅스 강남역점", "amount": 5600, "memo": None}
    assert a["ok"][0].row_number == 5
    assert -45000 in [r.tx["amount"] for r in a["ok"]]
    assert sum(r.tx["amount"] for r in a["ok"]) == 278_350


def test_card_b_datetime_cell_string_amounts_errors():
    b = analyze(load("card-b.xlsx"))
    assert b["hi"] == 1
    assert b["names"] == {"date": "거래일시", "merchant": "이용하신곳", "amount": "승인금액", "memo": "비고"}
    assert [b["header"][c] for c in b["sensitive"]] == ["카드번호"]
    txs = [r.tx for r in b["ok"]]
    assert txs[0]["date"] == "2026-09-03" and txs[0]["time"] == "08:12:45" and txs[0]["amount"] == 4500
    assert next(t for t in txs if t["merchant"] == "다이소")["amount"] == -5000
    assert len(b["ok"]) == 7
    assert [(e.row_number, e.reason) for e in b["errors"]] == [(7, "날짜 형식 오류"), (8, "금액 형식 오류")]
    assert "1234-" not in repr(txs)
    assert sum(t["amount"] for t in txs) == 61_020


def test_bank_c_euc_kr_csv():
    c = analyze(load("bank-c.csv"))
    assert c["names"] == {"date": "거래일자", "time": "거래시간", "merchant": "적요", "amount": "출금액", "memo": "내용"}
    assert [c["header"][col] for col in c["sensitive"]] == ["계좌번호"]
    assert len(c["ok"]) == 4
    assert c["ok"][0].tx == {"date": "2026-09-01", "time": "09:15:00", "merchant": "스타벅스", "amount": 6100, "memo": "체크카드"}
    assert [e.reason for e in c["errors"]] == ["금액 0원"]


def test_preset_by_header_name_survives_reordering():
    table = load("card-b.xlsx")
    header = table.rows[1]
    preset = to_preset_mapping(header, guess_mapping(header, {1}))
    reordered = list(reversed(header))
    applied = from_preset_mapping(reordered, preset)
    assert applied["date"] == reordered.index("거래일시")
    assert applied["amount"] == reordered.index("승인금액")
    assert from_preset_mapping(["날짜", "가게", "금액"], preset) is None


def test_duplicates_by_count():
    a = analyze(load("card-a.xlsx"))
    existing = [r.tx for r in a["ok"]]
    assert all(r.duplicate for r in mark_duplicates(a["ok"], existing))
    a = analyze(load("card-a.xlsx"))
    starbucks = [t for t in existing if t["date"] == "2026-09-12"]
    assert len(starbucks) == 2
    marked = mark_duplicates(a["ok"], [starbucks[0]])
    assert [r.duplicate for r in marked if r.tx["date"] == "2026-09-12"] == [True, False]
    err = RowResult(1, "error", reason="x")
    assert mark_duplicates([err], existing) == [err]


def test_5000_rows_under_3_seconds():
    wb = Workbook()
    ws = wb.active
    ws.append(["카드 이용내역"])
    ws.append([])
    ws.append(["이용일자", "가맹점명", "이용금액", "비고"])
    for i in range(5000):
        ws.append([f"2026.{i % 12 + 1:02d}.{i % 28 + 1:02d}", f"가게{i % 300}", f"{(i % 90) * 100 + 1000}원", None])
    buf = io.BytesIO()
    wb.save(buf)
    start = time.perf_counter()
    result = analyze(read_workbook(buf.getvalue(), "big.xlsx"))
    marked = mark_duplicates(result["ok"], [])
    assert len(marked) == 5000
    assert time.perf_counter() - start < 3
