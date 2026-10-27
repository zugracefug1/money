"""거래 내역: 기간·항목·검색 필터, 항목 바로 수정(규칙 저장 제안), 미분류 사용처별 일괄 지정, AI 추천."""

import pandas as pd
import streamlit as st

from gagyebu import ai, store, ui
from gagyebu.analysis import link_refunds
from gagyebu.classify import base_merchant_name
from gagyebu.export import workbook_bytes

st.title("거래 내역")
d = ui.data()
if not d["transactions"]:
    st.info("아직 거래가 없습니다. 업로드 화면에서 엑셀을 올려 주세요.", icon=":material/info:")
    st.stop()

BY_LABEL = {"rule": "자동", "ai": "AI", "manual": "수동", None: ""}
NONE_LABEL = "미분류"
cat_ids = ui.category_options()
label_to_id = {ui.label(c): c for c in cat_ids}
labels = list(label_to_id)


def suggest_rules(changes: list[tuple[str, str]]) -> None:
    """수정한 사용처마다 "앞으로도 이 항목으로 분류할까요?"를 묻는다."""
    pending = st.session_state.setdefault("rule_suggestions", {})
    for merchant, cid in changes:
        pending[base_merchant_name(merchant)] = cid


# 규칙 저장 제안 -------------------------------------------------------------------------
pending = st.session_state.get("rule_suggestions", {})
for keyword, cid in list(pending.items()):
    with st.container(border=True):
        c1, c2, c3 = st.columns([6, 1, 1], vertical_alignment="center")
        c1.markdown(f"앞으로 **'{keyword}'** 는 항상 **{ui.label(cid)}** 로 분류할까요?")
        if c2.button("규칙 저장", key=f"rule_yes_{keyword}", type="primary"):
            rule = store.upsert_rule(d, keyword, cid)
            n = store.apply_rule(d, rule)
            pending.pop(keyword)
            ui.touch()
            ui.flash(f"규칙을 저장하고 같은 사용처 {n}건에 적용했습니다.")
            st.rerun()
        if c3.button("아니요", key=f"rule_no_{keyword}"):
            pending.pop(keyword)
            st.rerun()

tab_default = st.session_state.pop("tx_tab", None) or st.session_state.get("tx_tab_widget") or "전체"
unclassified_count = sum(1 for t in d["transactions"] if not t.get("category_id"))
tab = st.segmented_control(
    "보기", ["전체", "미분류"], default=tab_default, key="tx_tab_widget", required=True,
    format_func=lambda v: f"미분류 {unclassified_count:,}건" if v == "미분류" else v, label_visibility="collapsed",
)  # fmt: skip

# 전체 ---------------------------------------------------------------------------------
if tab == "전체":
    period = ui.period_picker()
    filter_options = ["all", "none", *cat_ids]
    wanted = st.session_state.pop("tx_category", None)
    c1, c2 = st.columns([2, 3])
    category = c1.selectbox(
        "항목", filter_options, index=filter_options.index(wanted) if wanted in filter_options else 0,
        format_func=lambda k: "전체 항목" if k == "all" else ui.label(None if k == "none" else k),
    )  # fmt: skip
    search = c2.text_input("검색", placeholder="사용처·메모 검색")
    txs = store.filter_transactions(d, period.start, period.end, ... if category == "all" else (None if category == "none" else category), search)
    st.caption(f"{period.label} · {len(txs):,}건 · 합계 {ui.won(sum(t['amount'] for t in txs))}")

    links = link_refunds(txs)
    df = pd.DataFrame(
        [
            {
                "id": t["id"], "날짜": t["date"], "시간": (t.get("time") or "")[:5], "사용처": t["merchant"], "금액": t["amount"],
                "항목": ui.label(t.get("category_id")), "분류": BY_LABEL.get(t.get("classified_by"), ""),
                "취소 짝": (f"{links[t['id']]['pair_date']} 취소됨" if links[t["id"]]["role"] == "original" else f"{links[t['id']]['pair_date']} 결제 취소") if t["id"] in links else "",
                "메모": t.get("memo") or "",
            }
            for t in txs
        ]
    ).set_index("id") if txs else pd.DataFrame(columns=["날짜", "시간", "사용처", "금액", "항목", "분류", "취소 짝", "메모"])  # fmt: skip

    editor_key = f"tx_editor_{st.session_state.get('rev', 0)}"

    def _apply_edits():
        edited = st.session_state[editor_key]["edited_rows"]
        changes = []
        for row_pos, patch in edited.items():
            if "항목" not in patch:
                continue
            tid = df.index[int(row_pos)]
            cid = label_to_id.get(patch["항목"])  # "미분류"·빈 값 → None
            store.set_category(d, {tid}, cid, "manual")
            tx = next(t for t in d["transactions"] if t["id"] == tid)
            if cid:
                changes.append((tx["merchant"], cid))
        if changes:
            suggest_rules(changes)
        ui.touch()

    st.data_editor(
        df,
        key=editor_key,
        on_change=_apply_edits,
        hide_index=True,
        disabled=["날짜", "시간", "사용처", "금액", "분류", "취소 짝", "메모"],
        column_config={
            "금액": st.column_config.NumberColumn("금액(원)", format="localized"),
            "항목": st.column_config.SelectboxColumn("항목", options=[NONE_LABEL, *labels], required=True, help="바꾸면 수동 분류로 저장되고, 규칙으로 저장할지 묻습니다"),
            "분류": st.column_config.TextColumn(help="자동: 규칙·기본 사전 / AI: AI 추천 수락 / 수동: 직접 지정"),
        },
        height=min(max(38 + 35 * len(df), 320), 640),  # 행이 적어도 항목 드롭다운이 가려지지 않는 높이
    )
    st.download_button(
        "이 목록 엑셀로 내려받기",
        workbook_bytes({"거래 내역": [{"날짜": t["date"], "시간": t.get("time") or "", "사용처": t["merchant"], "금액": t["amount"], "항목": ui.label(t.get("category_id")), "메모": t.get("memo") or ""} for t in txs]}),
        file_name=f"거래내역-{period.start}_{period.end}.xlsx",
        icon=":material/download:",
    )

# 미분류 --------------------------------------------------------------------------------
else:
    groups: dict[str, list[dict]] = {}
    for t in d["transactions"]:
        if not t.get("category_id"):
            groups.setdefault(base_merchant_name(t["merchant"]), []).append(t)
    if not groups:
        st.success("미분류 거래가 없습니다.", icon=":material/task_alt:")
        st.stop()

    st.caption("같은 사용처끼리 묶었습니다. 항목을 고르고 적용하면 묶음 전체가 바뀌고, '규칙'에 체크하면 다음 업로드부터 자동 분류됩니다.")
    ai_suggest: dict[str, str] = st.session_state.get("ai_suggest", {})

    if ai.is_configured():
        if st.button("AI 추천 받기", icon=":material/auto_awesome:", help="사용처 이름과 항목 이름만 보냅니다(금액·날짜 제외). 추천은 수락해야 저장됩니다."):
            names = [c["name"] for c, _ in store.ordered_categories(d)]
            merchants = sorted(groups, key=lambda k: -len(groups[k]))[: ai.AI_MAX_MERCHANTS]
            try:
                with st.spinner("AI가 사용처를 분류하는 중..."):
                    result = ai.suggest_categories(merchants, names)
                by_name = {c["name"]: c["id"] for c in d["categories"]}
                st.session_state.ai_suggest = ai_suggest = {r["merchant"]: by_name[r["category"]] for r in result}
                st.toast(f"{len(ai_suggest)}곳을 추천했습니다. 확인 후 적용하세요.", icon=":material/auto_awesome:")
            except ai.AiError as e:
                st.error(str(e), icon=":material/error:")
    else:
        st.caption("AI 추천: 설정되지 않았습니다(ANTHROPIC_API_KEY).")

    gdf = pd.DataFrame(
        [
            {
                "사용처": name, "건수": len(items), "합계": sum(t["amount"] for t in items),
                "예": ", ".join(sorted({t["merchant"] for t in items})[:3]),
                "항목": ui.label(ai_suggest[name]) if name in ai_suggest else None,
                "AI 추천": "AI" if name in ai_suggest else "", "규칙": True,
            }
            for name, items in sorted(groups.items(), key=lambda kv: -len(kv[1]))
        ]
    )  # fmt: skip
    edited = st.data_editor(
        gdf,
        key=f"group_editor_{st.session_state.get('rev', 0)}",
        hide_index=True,
        height=min(max(38 + 35 * len(gdf), 320), 640),  # 행이 적어도 항목 드롭다운이 가려지지 않는 높이
        disabled=["사용처", "건수", "합계", "예", "AI 추천"],
        column_config={
            "합계": st.column_config.NumberColumn("합계(원)", format="localized"),
            "항목": st.column_config.SelectboxColumn("항목", options=labels),
            "규칙": st.column_config.CheckboxColumn("규칙 저장", help="이 사용처를 앞으로도 이 항목으로 자동 분류"),
        },
    )
    chosen = edited[edited["항목"].notna()]
    if st.button(f"선택한 {len(chosen)}곳 적용", type="primary", disabled=chosen.empty):
        moved = 0
        for _, row in chosen.iterrows():
            cid = label_to_id[row["항목"]]
            by = "ai" if ai_suggest.get(row["사용처"]) == cid else "manual"
            moved += store.set_category(d, {t["id"] for t in groups[row["사용처"]]}, cid, by)
            if row["규칙"]:
                store.apply_rule(d, store.upsert_rule(d, row["사용처"], cid), "ai" if by == "ai" else "rule")
        st.session_state.pop("ai_suggest", None)
        ui.touch()
        ui.flash(f"{moved}건을 분류했습니다.")
        st.rerun()
