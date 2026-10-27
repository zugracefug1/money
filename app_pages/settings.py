"""설정: 항목·예산, 분류 규칙, 열 매핑 양식, 데이터 백업·초기화."""

import re

import pandas as pd
import streamlit as st

from gagyebu import store, ui

st.title("설정")
d = ui.data()
rev = st.session_state.get("rev", 0)
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

# 항목과 월 예산 --------------------------------------------------------------------------
st.subheader("항목과 월 예산")
st.caption("예산을 정하면 대시보드에 예산 대비 사용률이 표시됩니다. '기타' 항목은 지우거나 이름을 바꿀 수 없습니다.")
ordered = store.ordered_categories(d)
cdf = pd.DataFrame(
    [
        {"id": c["id"], "이름": c["name"], "상위 항목": ui.label(c["parent_id"]) if c.get("parent_id") else "", "색": c["color"], "월 예산": c.get("monthly_budget"), "삭제": False}
        for c, _ in ordered
    ]
).set_index("id")
cdf["월 예산"] = pd.to_numeric(cdf["월 예산"], errors="coerce").fillna(0).astype(int)  # 0 = 예산 없음
edited = st.data_editor(
    cdf,
    key=f"cat_editor_{rev}",
    hide_index=True,
    height=38 + 35 * len(cdf),
    disabled=["상위 항목"],
    column_config={
        "이름": st.column_config.TextColumn(required=True, max_chars=30),
        "색": st.column_config.TextColumn("색(#RRGGBB)", validate=r"^#[0-9a-fA-F]{6}$"),
        "월 예산": st.column_config.NumberColumn("월 예산(원)", min_value=0, format="localized", help="0이면 예산을 정하지 않은 것으로 봅니다"),
        "삭제": st.column_config.CheckboxColumn(help="소속 거래는 '기타'로 옮겨지고, 하위 항목과 그 규칙도 지워집니다"),
    },
)
if st.button("항목 변경 저장", type="primary"):
    try:
        changed = deleted = 0
        etc = store.etc_id(d)
        for cid, row in edited.iterrows():
            orig = cdf.loc[cid]
            if row["삭제"]:
                if cid == etc:
                    raise store.StoreError("'기타' 항목은 지울 수 없습니다.")
                continue
            patch = {}
            if row["이름"] != orig["이름"]:
                patch["name"] = row["이름"]
            if row["색"] != orig["색"]:
                if not HEX.match(str(row["색"])):
                    raise store.StoreError(f"'{row['이름']}' 색은 #RRGGBB 형식이어야 합니다.")
                patch["color"] = row["색"]
            budget = None if pd.isna(row["월 예산"]) or not row["월 예산"] else int(row["월 예산"])
            if budget != (None if pd.isna(orig["월 예산"]) or not orig["월 예산"] else int(orig["월 예산"])):
                patch["monthly_budget"] = budget
            if patch:
                store.update_category(d, cid, **patch)
                changed += 1
        for cid, row in edited.iterrows():
            if row["삭제"] and any(c["id"] == cid for c in d["categories"]):
                store.delete_category(d, cid)
                deleted += 1
        ui.touch()
        ui.flash(f"항목 {changed}개를 바꾸고 {deleted}개를 지웠습니다.")
        st.rerun()
    except store.StoreError as e:
        st.error(str(e), icon=":material/error:")

with st.form("add_category", clear_on_submit=True):
    st.markdown("**새 항목**")
    c1, c2, c3, c4 = st.columns([3, 3, 1, 2], vertical_alignment="bottom")
    name = c1.text_input("이름", placeholder="새 항목 이름")
    tops = [c["id"] for c, depth in ordered if depth == 0]
    parent = c2.selectbox("상위 항목", [None, *tops], format_func=lambda c: "최상위 항목" if c is None else f"{ui.label(c)}의 하위 항목")
    color = c3.color_picker("색", "#64748b")
    budget = c4.number_input("월 예산(원, 선택)", min_value=0, step=10000, value=0)
    if st.form_submit_button("추가"):
        try:
            store.add_category(d, name, color, parent, int(budget) or None)
            ui.touch()
            ui.flash(f"'{name.strip()}' 항목을 추가했습니다.")
            st.rerun()
        except store.StoreError as e:
            st.error(str(e), icon=":material/error:")

# 분류 규칙 -------------------------------------------------------------------------------
st.subheader("분류 규칙")
st.caption("사용처 이름에 키워드가 들어 있으면(포함) 또는 같으면(일치) 그 항목으로 분류합니다. 우선순위가 높은 규칙이 먼저 적용됩니다. 행을 지우거나 추가할 수 있습니다.")
cat_ids = ui.category_options()
label_to_id = {ui.label(c): c for c in cat_ids}
MATCH = {"contains": "포함", "equals": "일치"}
rdf = pd.DataFrame(
    [{"키워드": r["keyword"], "방식": MATCH.get(r["match_type"], "포함"), "항목": ui.label(r["category_id"]), "우선순위": r.get("priority") or 0} for r in store.ordered_rules(d)],
    columns=["키워드", "방식", "항목", "우선순위"],
)
redited = st.data_editor(
    rdf,
    key=f"rule_editor_{rev}",
    hide_index=True,
    num_rows="dynamic",
    column_config={
        "키워드": st.column_config.TextColumn(required=True),
        "방식": st.column_config.SelectboxColumn(options=list(MATCH.values()), required=True, default="포함"),
        "항목": st.column_config.SelectboxColumn(options=list(label_to_id), required=True),
        "우선순위": st.column_config.NumberColumn(min_value=0, max_value=100, step=1, default=0),
    },
)
c1, c2, _ = st.columns([1, 1, 3])
if c1.button("규칙 저장", type="primary"):
    rules = []
    for _, row in redited.iterrows():
        if not str(row["키워드"] or "").strip() or row["항목"] not in label_to_id:
            continue
        match_type = "equals" if row["방식"] == "일치" else "contains"
        rules.append({"keyword": str(row["키워드"]).strip(), "match_type": match_type, "category_id": label_to_id[row["항목"]], "priority": int(row["우선순위"] or 0)})
    d["rules"] = []
    for r in rules:
        store.upsert_rule(d, r["keyword"], r["category_id"], r["match_type"], r["priority"])
    ui.touch()
    ui.flash(f"규칙 {len(d['rules'])}개를 저장했습니다.")
    st.rerun()
if c2.button("규칙 다시 적용", help="수동으로 지정한 거래를 뺀 모든 거래에 규칙을 우선순위 순서로 다시 적용합니다"):
    n = 0
    for r in reversed(store.ordered_rules(d)):  # 우선순위가 높은 규칙이 마지막에 덮어쓰도록
        n += store.apply_rule(d, r)
    ui.touch()
    ui.flash(f"거래 {n}건의 항목을 바꿨습니다.")
    st.rerun()

# 열 매핑 양식 ----------------------------------------------------------------------------
st.subheader("열 매핑 양식")
if d["column_presets"]:
    for p in sorted(d["column_presets"], key=lambda p: p["name"]):
        c1, c2 = st.columns([5, 1], vertical_alignment="center")
        cols = (p.get("mapping") or {}).get("columns") or {}
        c1.markdown(f"**{p['name']}** — " + ", ".join(f"{k}: {v}" for k, v in cols.items()))
        if c2.button("삭제", key=f"preset_del_{p['id']}"):
            d["column_presets"] = [x for x in d["column_presets"] if x["id"] != p["id"]]
            ui.touch()
            st.rerun()
else:
    st.caption("저장한 양식이 없습니다. 업로드할 때 열 매핑을 양식으로 저장할 수 있습니다.")

# 데이터 ---------------------------------------------------------------------------------
st.subheader("데이터")
st.markdown(
    "데이터는 이 브라우저 세션에만 있습니다. 새로고침하거나 창을 닫으면 사라지므로, 사이드바의 **백업 파일 내려받기**로 저장해 두고 "
    "다음에 **백업 파일 불러오기**로 이어서 쓰세요."
)
with st.expander("내 데이터 전체 삭제"):
    st.warning("거래·규칙·양식·업로드 이력을 모두 지우고 기본 항목만 남깁니다. 되돌릴 수 없으니 먼저 백업 파일을 내려받으세요.", icon=":material/warning:")
    sure = st.checkbox("모두 지우는 데 동의합니다")
    if st.button("전체 삭제", type="primary", disabled=not sure):
        ui.replace_data(store.new_store())
        ui.flash("데이터를 모두 지웠습니다.")
        st.rerun()
