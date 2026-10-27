"""여러 페이지가 함께 쓰는 Streamlit 도우미: 세션 데이터, 기간 선택, 표시 형식."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import streamlit as st

from . import store
from .classify import create_classifier
from .importer import build_rows, find_header_row, find_sensitive_columns, guess_mapping, read_workbook
from .period import Period, add_months, custom_period, month_label, month_of, month_period, quarter_period, today_in_seoul, year_period

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
PAGES = {
    "dashboard": "app_pages/dashboard.py",
    "upload": "app_pages/upload.py",
    "transactions": "app_pages/transactions.py",
    "analysis": "app_pages/analysis.py",
    "settings": "app_pages/settings.py",
}


def data() -> dict:
    """이 브라우저 세션의 가계부 데이터. 서버 디스크에는 저장하지 않는다."""
    if "data" not in st.session_state:
        st.session_state.data = store.new_store()
        st.session_state.rev = 0
        st.session_state.saved_rev = 0
    return st.session_state.data


def touch() -> None:
    """데이터가 바뀌었음을 기록한다(백업 이후 변경 여부 표시용)."""
    st.session_state.rev = st.session_state.get("rev", 0) + 1


def replace_data(new: dict) -> None:
    st.session_state.data = new
    st.session_state.rev = st.session_state.get("rev", 0) + 1
    st.session_state.saved_rev = st.session_state.rev


def classifier():
    d = data()
    return create_classifier(d["rules"], d["categories"])


def won(n: float) -> str:
    return f"{int(round(n)):,}원"


def label(cid: str | None) -> str:
    return store.category_label(data(), cid)


def category_options(include_none: bool = False) -> list[str | None]:
    opts: list[str | None] = [c["id"] for c, _ in store.ordered_categories(data())]
    return ([None] + opts) if include_none else opts


def flash(message: str, icon: str = ":material/check_circle:") -> None:
    """다음 rerun 에서 토스트로 보여 줄 메시지(콜백 안에서 부를 때)"""
    st.session_state.setdefault("_flash", []).append((message, icon))


def show_flash() -> None:
    for message, icon in st.session_state.pop("_flash", []):
        st.toast(message, icon=icon)


def load_samples() -> int:
    """samples/ 의 합성 파일을 앱과 같은 순서로 읽어 저장한다(체험용)."""
    d = data()
    classify = classifier()
    total = 0
    for f in sorted(SAMPLES.glob("*")):
        if f.suffix.lower() not in (".xlsx", ".xls", ".csv"):
            continue
        table = read_workbook(f.read_bytes(), f.name)
        hi = find_header_row(table.rows)
        header = table.rows[hi]
        mapping = guess_mapping(header, find_sensitive_columns(header, table.rows[hi + 1 :]))
        rows = [r.tx for r in build_rows(table, hi, mapping)[0] if r.status == "ok"]
        store.import_rows(d, f.name, "샘플", rows, classify)
        total += len(rows)
    touch()
    return total


# 기간 선택 ----------------------------------------------------------------------------

MODES = {"month": "월", "quarter": "분기", "year": "연", "custom": "직접 지정"}


def _default_month() -> str:
    """가장 최근 거래가 있는 달(없으면 이번 달)"""
    txs = data()["transactions"]
    return month_of(max(t["date"] for t in txs)) if txs else month_of(today_in_seoul())


def _month_choices() -> list[str]:
    txs = data()["transactions"]
    today = month_of(today_in_seoul())
    if not txs:
        return [add_months(today, -i) for i in range(12)]
    first = month_of(min(t["date"] for t in txs))
    last = max(month_of(max(t["date"] for t in txs)), today)
    out, m = [], last
    while m >= first:
        out.append(m)
        m = add_months(m, -1)
    return out


def period_picker(key: str = "period") -> Period:
    """월·분기·연·직접 지정. 선택은 세션에 남아 대시보드와 거래 내역이 같은 기간을 공유한다."""
    months = _month_choices()
    state = st.session_state.setdefault(key, {"mode": "month", "month": _default_month()})
    if state.get("month") not in months:
        state["month"] = months[0]

    c1, c2 = st.columns([2, 3], vertical_alignment="bottom")
    with c1:
        mode = st.segmented_control(
            "기간", list(MODES), format_func=MODES.get, default=state["mode"], key=f"{key}_mode", required=True
        )
    state["mode"] = mode or "month"
    with c2:
        if state["mode"] == "month":
            ym = st.selectbox("월", months, index=months.index(state["month"]), format_func=month_label, key=f"{key}_month", label_visibility="collapsed")
            state["month"] = ym
            return month_period(ym)
        if state["mode"] == "quarter":
            quarters = list(dict.fromkeys(f"{m[:4]}-Q{(int(m[5:7]) - 1) // 3 + 1}" for m in months))
            cur = f"{state['month'][:4]}-Q{(int(state['month'][5:7]) - 1) // 3 + 1}"
            q = st.selectbox("분기", quarters, index=quarters.index(cur), format_func=lambda v: f"{v[:4]}년 {v[-1]}분기", key=f"{key}_q", label_visibility="collapsed")
            state["month"] = f"{q[:4]}-{(int(q[-1]) - 1) * 3 + 1:02d}" if f"{q[:4]}-{(int(q[-1]) - 1) * 3 + 1:02d}" in months else state["month"]
            return quarter_period(int(q[:4]), int(q[-1]))
        if state["mode"] == "year":
            years = list(dict.fromkeys(m[:4] for m in months))
            y = st.selectbox("연도", years, index=years.index(state["month"][:4]), format_func=lambda v: f"{v}년", key=f"{key}_y", label_visibility="collapsed")
            return year_period(int(y))
        start, end = month_period(state["month"]).start, month_period(state["month"]).end
        picked = st.date_input("기간", (date.fromisoformat(start), date.fromisoformat(end)), key=f"{key}_custom", label_visibility="collapsed")
        if isinstance(picked, (tuple, list)) and len(picked) == 2:
            return custom_period(picked[0].isoformat(), picked[1].isoformat())
        return custom_period(start, end)
