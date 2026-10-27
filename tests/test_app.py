"""모든 화면이 예외 없이 그려지는지 Streamlit AppTest 로 확인한다(빈 상태 → 샘플 데이터)."""

import pytest
from streamlit.testing.v1 import AppTest

from gagyebu import ui

PAGES = list(ui.PAGES.values())


def run(at: AppTest) -> AppTest:
    at.run(timeout=30)
    assert not at.exception, [e.value for e in at.exception]
    return at


@pytest.mark.parametrize("page", PAGES)
def test_pages_render_empty(page):
    at = run(AppTest.from_file("../streamlit_app.py"))
    run(at.switch_page(page))


def test_samples_then_every_page():
    at = run(AppTest.from_file("../streamlit_app.py"))
    next(b for b in at.button if b.label == "샘플 데이터 불러오기").click()
    run(at)
    assert len(at.session_state.data["transactions"]) == 13 + 7 + 4
    # 대시보드(가장 최근 거래가 있는 2026년 9월) 총지출 = 샘플 9월 거래 합계(환불 차감)
    txs = at.session_state.data["transactions"]
    sept = sum(t["amount"] for t in txs if t["date"].startswith("2026-09"))
    by_file = {b["file_name"]: sum(t["amount"] for t in txs if t["batch_id"] == b["id"]) for b in at.session_state.data["import_batches"]}
    assert by_file["card-a.xlsx"] == 278_350 and by_file["card-b.xlsx"] == 61_020
    total = next(m for m in at.metric if m.label.endswith("총지출"))
    assert total.label == "2026년 9월 총지출"
    assert total.value == f"{sept:,}원"
    for page in PAGES:
        run(at.switch_page(page))


def test_backup_roundtrip_through_session():
    at = run(AppTest.from_file("../streamlit_app.py"))
    next(b for b in at.button if b.label == "샘플 데이터 불러오기").click()
    run(at)
    from gagyebu import store

    data = at.session_state.data
    assert store.load_backup(store.dump_backup(data))["transactions"] == data["transactions"]
