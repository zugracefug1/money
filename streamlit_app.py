"""가계부 — 카드사·은행 엑셀을 올리면 사용처별로 분류하고 항목별 지출과 소비 패턴을 보여 준다.

실행: streamlit run streamlit_app.py
데이터는 브라우저 세션(서버 메모리)에만 있고, 사이드바의 백업 파일로 이어서 쓴다.
"""

import streamlit as st

from gagyebu import store, ui

st.set_page_config(page_title="가계부", page_icon=":material/account_balance_wallet:", layout="wide")

pages = [
    st.Page(ui.PAGES["dashboard"], title="대시보드", icon=":material/dashboard:", default=True),
    st.Page(ui.PAGES["upload"], title="업로드", icon=":material/upload_file:"),
    st.Page(ui.PAGES["transactions"], title="거래 내역", icon=":material/receipt_long:"),
    st.Page(ui.PAGES["analysis"], title="분석", icon=":material/insights:"),
    st.Page(ui.PAGES["settings"], title="설정", icon=":material/settings:"),
]
current = st.navigation(pages)

d = ui.data()


def _restore():
    file = st.session_state.get("restore_file")
    if not file:
        return
    try:
        ui.replace_data(store.load_backup(file.getvalue()))
        ui.flash(f"백업을 불러왔습니다: 거래 {len(st.session_state.data['transactions']):,}건")
    except store.StoreError as e:
        ui.flash(str(e), ":material/error:")


def _mark_saved():
    st.session_state.saved_rev = st.session_state.get("rev", 0)


with st.sidebar:
    st.subheader("내 데이터")
    st.caption(f"거래 {len(d['transactions']):,}건 · 규칙 {len(d['rules'])}개")
    unsaved = st.session_state.get("rev", 0) != st.session_state.get("saved_rev", 0)
    if unsaved and d["transactions"]:
        st.warning("백업 이후 바뀐 내용이 있습니다. 새로고침하거나 창을 닫으면 사라집니다.", icon=":material/warning:")
    st.download_button(
        "백업 파일 내려받기",
        data=store.dump_backup(d),
        file_name="gagyebu-data.json",
        mime="application/json",
        icon=":material/download:",
        on_click=_mark_saved,
        width="stretch",
    )
    st.file_uploader("백업 파일 불러오기", type=["json"], key="restore_file", on_change=_restore, help="내려받아 둔 gagyebu-data.json (로컬판 데이터 파일도 됩니다)")
    st.caption("데이터는 이 브라우저 세션에만 있고 서버에 저장되지 않습니다. 원본 엑셀과 카드번호도 저장하지 않습니다.")

ui.show_flash()
current.run()
