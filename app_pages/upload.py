"""업로드: 엑셀/CSV → 헤더·열 자동 감지(수정 가능) → 미리보기·오류·중복 → 저장(자동 분류). 업로드 이력과 되돌리기."""

import pandas as pd
import streamlit as st

from gagyebu import store, ui
from gagyebu.importer import (
    FIELD_LABELS,
    FIELDS,
    MAX_FILE_BYTES,
    REQUIRED_FIELDS,
    build_rows,
    find_header_row,
    find_sensitive_columns,
    from_preset_mapping,
    guess_mapping,
    header_signature,
    is_preset_mapping,
    mark_duplicates,
    read_workbook,
    to_preset_mapping,
)

st.title("업로드")
st.caption("카드사·은행에서 내려받은 .xlsx · .xls · .csv (최대 10MB). 파일은 메모리에서만 읽고 저장하지 않으며, 카드번호·계좌번호 열은 저장하지 않습니다.")
d = ui.data()

uploader_key = f"upload_{st.session_state.get('upload_seq', 0)}"
file = st.file_uploader("거래내역 파일", type=["xlsx", "xls", "csv"], key=uploader_key)


def _read(file_id: str, name: str, raw: bytes):
    """읽은 표는 이 세션에만 보관한다(st.cache_data 는 세션 사이에 공유되므로 금융 내역에 쓰지 않는다)."""
    cached = st.session_state.get("_upload_table")
    if cached and cached[0] == file_id:
        return cached[1]
    with st.spinner("파일을 읽는 중..."):
        table = read_workbook(raw, name)
    st.session_state._upload_table = (file_id, table)
    return table


def _col_name(header, col):
    h = header[col] if col < len(header) else None
    return f"{col + 1}열: {h}" if h not in (None, "") else f"{col + 1}열"


if file is not None:
    raw = file.getvalue()
    if len(raw) > MAX_FILE_BYTES:
        st.error("파일이 10MB보다 큽니다. 기간을 나눠서 내려받아 주세요.", icon=":material/error:")
        st.stop()
    try:
        table = _read(file.file_id, file.name, raw)
    except Exception as e:  # 손상된 파일, 암호 걸린 엑셀 등
        st.error(f"파일을 읽지 못했습니다: {e}", icon=":material/error:")
        st.stop()

    # 1) 헤더 행
    auto_header = find_header_row(table.rows)
    header_row_no = st.number_input(
        "헤더(열 이름) 행 번호", min_value=table.first_row_number, max_value=table.first_row_number + len(table.rows) - 1,
        value=table.first_row_number + auto_header, help="제목·조회기간 같은 머리말 아래의 실제 열 이름 행. 자동으로 찾았습니다.",
        key=f"hdr_{file.file_id}",
    )  # fmt: skip
    hi = int(header_row_no) - table.first_row_number
    header = table.rows[hi]
    sensitive = find_sensitive_columns(header, table.rows[hi + 1 :])
    if sensitive:
        st.info("카드번호·계좌번호로 보이는 열은 저장하지 않습니다: " + ", ".join(_col_name(header, c) for c in sorted(sensitive)), icon=":material/shield:")

    # 2) 열 매핑: 저장해 둔 양식(같은 헤더) → 자동 추측
    preset_used = None
    mapping = None
    sig = header_signature(header)
    for p in d["column_presets"]:
        if is_preset_mapping(p.get("mapping")) and p["mapping"]["signature"] == sig:
            mapping = from_preset_mapping(header, p["mapping"], sensitive)
            if mapping:
                preset_used = p["name"]
                break
    if mapping is None:
        mapping = guess_mapping(header, sensitive)
    if preset_used:
        st.success(f"저장해 둔 열 매핑 양식 '{preset_used}'을(를) 적용했습니다.", icon=":material/bookmark:")

    st.subheader("열 매핑")
    cols = [c for c in range(max(len(r) for r in table.rows[hi : hi + 50])) if c not in sensitive]
    picks = st.columns(len(FIELDS))
    chosen: dict[str, int] = {}
    for i, f in enumerate(FIELDS):
        options = [None, *cols]
        current = mapping.get(f)
        value = picks[i].selectbox(
            FIELD_LABELS[f] + (" *" if f in REQUIRED_FIELDS else " (선택)"), options,
            index=options.index(current) if current in options else 0,
            format_func=lambda c: "선택 안 함" if c is None else _col_name(header, c),
            key=f"map_{file.file_id}_{hi}_{f}",
        )  # fmt: skip
        if value is not None:
            chosen[f] = value
    if len(set(chosen.values())) < len(chosen):
        st.error("한 열을 두 항목에 지정했습니다. 열을 다시 골라 주세요.", icon=":material/error:")
        st.stop()
    missing = [FIELD_LABELS[f] for f in REQUIRED_FIELDS if f not in chosen]
    if missing:
        st.warning(f"{', '.join(missing)} 열을 골라 주세요.", icon=":material/warning:")
        st.stop()

    # 3) 변환·중복 확인
    results, skipped = build_rows(table, hi, chosen)
    ok = [r for r in results if r.status == "ok"]
    errors = [r for r in results if r.status == "error"]
    if ok:
        lo, hi_date = min(r.tx["date"] for r in ok), max(r.tx["date"] for r in ok)
        mark_duplicates(ok, store.filter_transactions(d, lo, hi_date))
    dups = sum(1 for r in ok if r.duplicate)
    classify = ui.classifier()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("정상", f"{len(ok):,}건", border=True)
    m2.metric("중복", f"{dups:,}건", border=True, help="같은 날짜·사용처·금액 거래가 이미 있는 행(건수 기준)")
    m3.metric("오류(제외)", f"{len(errors):,}건", border=True)
    m4.metric("합계(중복 제외)", ui.won(sum(r.tx["amount"] for r in ok if not r.duplicate)), border=True)
    if skipped:
        st.caption(f"빈 행·합계 행 {skipped}개는 건너뛰었습니다.")

    st.subheader("미리보기 (위 20행)")
    preview = []
    for r in results[:20]:
        if r.status == "ok":
            cid = classify(r.tx["merchant"])
            preview.append({"행": r.row_number, "상태": "중복" if r.duplicate else "정상", "날짜": r.tx["date"], "시간": (r.tx["time"] or "")[:5], "사용처": r.tx["merchant"], "금액": r.tx["amount"], "자동 분류": ui.label(cid) if cid else "미분류", "메모": r.tx["memo"] or ""})
        else:
            cells = {f: r.cells[c] if c < len(r.cells) else None for f, c in chosen.items()}
            preview.append({"행": r.row_number, "상태": f"오류: {r.reason}", "날짜": str(cells.get("date") or ""), "시간": "", "사용처": str(cells.get("merchant") or ""), "금액": None, "자동 분류": "", "메모": str(cells.get("memo") or "")})
    pdf = pd.DataFrame(preview)

    def _row_style(row):
        if str(row["상태"]).startswith("오류"):
            return ["background-color: #fbebeb; color: #991b1b"] * len(row)
        if row["상태"] == "중복":
            return ["color: #6b7280"] * len(row)
        return [""] * len(row)

    st.dataframe(pdf.style.apply(_row_style, axis=1), hide_index=True, column_config={"금액": st.column_config.NumberColumn("금액(원)", format="localized")})
    if errors:
        with st.expander(f"오류 행 {len(errors)}건 모두 보기"):
            st.dataframe(pd.DataFrame([{"행": e.row_number, "이유": e.reason} for e in errors]), hide_index=True)

    # 4) 저장
    with st.form("save_upload", border=True):
        include_dups = st.radio("중복 거래", ["건너뛰기", "포함해서 저장"], horizontal=True, disabled=dups == 0) == "포함해서 저장"
        save_preset = st.checkbox("이 열 매핑을 양식으로 저장(같은 양식 파일에 자동 적용)", value=not preset_used)
        preset_name = st.text_input("양식 이름", value=preset_used or file.name.rsplit(".", 1)[0])
        submitted = st.form_submit_button("저장하기", type="primary", disabled=not ok)
    if submitted:
        rows = [r.tx for r in ok if include_dups or not r.duplicate]
        if not rows:
            st.warning("저장할 거래가 없습니다(모두 중복).", icon=":material/warning:")
        else:
            if save_preset:
                store.save_preset(d, preset_name, to_preset_mapping(header, chosen))
            batch = store.import_rows(d, file.name, preset_name if (save_preset or preset_used) else None, rows, classify)
            auto = sum(1 for t in d["transactions"] if t["batch_id"] == batch["id"] and t["category_id"])
            ui.touch()
            st.session_state.upload_seq = st.session_state.get("upload_seq", 0) + 1  # 업로더 비우기
            st.session_state.pop("_upload_table", None)
            ui.flash(f"{len(rows):,}건을 저장했습니다. 자동 분류 {auto:,}건, 미분류 {len(rows) - auto:,}건.")
            st.rerun()

# 업로드 이력 ---------------------------------------------------------------------------
if d["import_batches"]:
    st.subheader("업로드 이력")
    st.caption("되돌리기를 누르면 그 업로드로 들어온 거래가 모두 지워집니다.")
    for b in sorted(d["import_batches"], key=lambda b: b["imported_at"], reverse=True):
        c1, c2 = st.columns([5, 1], vertical_alignment="center")
        c1.markdown(f"**{b['file_name']}** · {b['row_count']:,}건 · {b['imported_at'][:16].replace('T', ' ')} (UTC)")
        if c2.button("되돌리기", key=f"undo_{b['id']}", icon=":material/undo:"):
            n = store.delete_batch(d, b["id"])
            ui.touch()
            ui.flash(f"업로드를 되돌려 거래 {n:,}건을 지웠습니다.")
            st.rerun()
elif file is None:
    if st.button("샘플 데이터로 먼저 둘러보기", icon=":material/science:"):
        n = ui.load_samples()
        ui.flash(f"샘플 거래 {n}건을 불러왔습니다.")
        st.switch_page(ui.PAGES["dashboard"])
