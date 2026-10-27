"""대시보드: 기간별 총지출, 전기간 대비, 항목별 비중·금액, 예산, 사용처 상위 10곳."""

import altair as alt
import pandas as pd
import streamlit as st

from gagyebu import store, ui
from gagyebu.export import workbook_bytes
from gagyebu.period import month_label, month_of

st.title("대시보드")
d = ui.data()

if not d["transactions"]:
    st.info("아직 거래가 없습니다. 카드사·은행 엑셀을 올리거나 샘플 데이터로 먼저 둘러보세요.", icon=":material/info:")
    c1, c2, _ = st.columns([1, 1, 3])
    if c1.button("엑셀 올리기", type="primary", icon=":material/upload_file:"):
        st.switch_page(ui.PAGES["upload"])
    if c2.button("샘플 데이터 불러오기", icon=":material/science:"):
        n = ui.load_samples()
        ui.flash(f"샘플 거래 {n}건을 불러왔습니다.")
        st.rerun()
    st.stop()

period = ui.period_picker()
txs = store.filter_transactions(d, period.start, period.end)
prev = store.filter_transactions(d, period.prev_start, period.prev_end)

if not txs:
    latest = month_of(max(t["date"] for t in d["transactions"]))
    st.info(f"{period.label}에는 거래가 없습니다.", icon=":material/info:")
    if st.button(f"가장 최근 거래가 있는 {month_label(latest)} 보기"):
        st.session_state.period = {"mode": "month", "month": latest}
        st.session_state.pop("period_mode", None)
        st.session_state.pop("period_month", None)
        st.rerun()
    st.stop()

# 항목별 합계(미분류 포함). 환불(음수)은 그대로 더해 순지출이 된다.
totals: dict[str | None, list[int]] = {}
for t in txs:
    e = totals.setdefault(t.get("category_id"), [0, 0])
    e[0] += t["amount"]
    e[1] += 1
total = sum(v[0] for v in totals.values())
prev_total = sum(t["amount"] for t in prev)
uncategorized = totals.get(None, [0, 0])[1]

c1, c2, c3, c4 = st.columns(4)
c1.metric(f"{period.label} 총지출", ui.won(total), border=True)
if prev_total > 0:
    diff = total - prev_total
    c2.metric(f"{period.prev_label} 대비", f"{'▲' if diff > 0 else '▼' if diff < 0 else ''} {ui.won(abs(diff))}", delta=f"{diff / prev_total:+.0%}", delta_color="inverse", border=True, help=f"{period.prev_label} {ui.won(prev_total)}")
else:
    c2.metric(f"{period.prev_label} 대비", "—", border=True, help=f"{period.prev_label}에는 비교할 거래가 없습니다")
c3.metric("거래 건수", f"{len(txs):,}건", border=True)
c4.metric("미분류", f"{uncategorized:,}건", border=True)
if uncategorized and c4.button("미분류 정리하기", type="tertiary", icon=":material/arrow_forward:"):
    st.session_state.tx_tab = "미분류"
    st.switch_page(ui.PAGES["transactions"])

# 차트는 순지출이 양수인 항목만(환불이 더 많은 항목은 비중을 그릴 수 없다)
rows = sorted(
    ({"cid": cid, "항목": ui.label(cid), "금액": v[0], "건수": v[1], "색": store.category_color(d, cid)} for cid, v in totals.items()),
    key=lambda r: -r["금액"],
)
positive = [r for r in rows if r["금액"] > 0]
pos_sum = sum(r["금액"] for r in positive) or 1
for r in rows:
    r["비중"] = r["금액"] / pos_sum if r["금액"] > 0 else None
    r["라벨"] = f"{ui.won(r['금액'])} ({r['비중']:.0%})" if r["비중"] else ui.won(r["금액"])

if positive:
    df = pd.DataFrame(positive)
    scale = alt.Scale(domain=list(df["항목"]), range=list(df["색"]))
    color = alt.Color("항목:N", scale=scale, legend=alt.Legend(title=None, orient="right"))
    tooltip = [alt.Tooltip("항목:N"), alt.Tooltip("금액:Q", format=","), alt.Tooltip("비중:Q", format=".1%"), alt.Tooltip("건수:Q")]
    left, right = st.columns(2)
    with left:
        st.subheader("항목별 비중")
        donut = alt.Chart(df).mark_arc(innerRadius=70, outerRadius=125, stroke="white").encode(theta="금액:Q", color=color, order=alt.Order("금액:Q", sort="descending"), tooltip=tooltip)
        st.altair_chart(donut.properties(height=320), alt=f"{period.label} 항목별 지출 비중 도넛 차트")
    with right:
        st.subheader("항목별 금액")
        # 정렬은 순서를 직접 넘긴다("-x"는 레이어 차트에서 무시된다). 오른쪽 라벨이 잘리지 않게 축에 여유를 둔다.
        base = alt.Chart(df).encode(
            y=alt.Y("항목:N", sort=list(df["항목"]), title=None),
            x=alt.X("금액:Q", title=None, axis=alt.Axis(format="~s"), scale=alt.Scale(domain=[0, int(df["금액"].max() * 1.45)])),
            tooltip=tooltip,
        )
        bars = base.mark_bar(cornerRadiusEnd=3).encode(color=alt.Color("항목:N", scale=scale, legend=None))
        text = base.mark_text(align="left", dx=4).encode(text="라벨:N")
        st.altair_chart((bars + text).properties(height=max(200, 36 * len(df))), alt=f"{period.label} 항목별 지출 막대 차트")

st.subheader("항목별 합계")
summary = pd.DataFrame([{"항목": r["항목"], "금액(원)": r["금액"], "비중": r["비중"] * 100 if r["비중"] else None, "건수": r["건수"]} for r in rows])
st.dataframe(
    summary,
    hide_index=True,
    column_config={"금액(원)": st.column_config.NumberColumn(format="localized"), "비중": st.column_config.NumberColumn(format="%.1f%%")},
)
# 미분류(None)는 선택 상자에서 "선택 안 함"과 구분되도록 "none" 으로 넘긴다
pick = st.selectbox(
    "항목의 거래 보기",
    [r["cid"] or "none" for r in rows],
    format_func=lambda k: ui.label(None if k == "none" else k),
    index=None,
    placeholder="항목을 고르면 그 기간의 거래 내역으로 이동합니다",
)
if pick is not None:
    st.session_state.tx_category = pick
    st.session_state.tx_tab = "전체"
    st.switch_page(ui.PAGES["transactions"])

# 예산: 월 예산 × 기간 개월 수와 비교
budgets = []
for c, _ in store.ordered_categories(d):
    if not c.get("monthly_budget"):
        continue
    budget = round(c["monthly_budget"] * period.months)
    used = totals.get(c["id"], [0, 0])[0]
    budgets.append((ui.label(c["id"]), used, budget, used / budget if budget else 0))
if budgets:
    note = "" if period.months == 1 else f" (월 예산 × {period.months:g}개월)"
    st.subheader(f"예산 대비 사용률{note}")
    for name, used, budget, ratio in sorted(budgets, key=lambda b: -b[3]):
        state = " · 초과" if ratio > 1 else " · 주의" if ratio >= 0.8 else ""
        st.progress(min(ratio, 1.0), text=f"**{name}**{state} — {ui.won(used)} / {ui.won(budget)} ({ratio:.0%})")

# 사용처 상위 10곳(순지출 기준)
merchants: dict[str, list] = {}
for t in txs:
    e = merchants.setdefault(t["merchant"], [0, 0, t.get("category_id")])
    e[0] += t["amount"]
    e[1] += 1
top = sorted(((m, v) for m, v in merchants.items() if v[0] > 0), key=lambda x: -x[1][0])[:10]
st.subheader("사용처별 합계 상위 10곳")
top_rows = [{"사용처": m, "항목": ui.label(v[2]), "횟수": v[1], "합계(원)": v[0]} for m, v in top]
st.dataframe(pd.DataFrame(top_rows), hide_index=True, column_config={"합계(원)": st.column_config.NumberColumn(format="localized")})

st.download_button(
    "이 기간 집계 엑셀로 내려받기",
    workbook_bytes(
        {
            "항목별 합계": [{"항목": r["항목"], "금액": r["금액"], "비중": f"{r['비중']:.1%}" if r["비중"] else "", "건수": r["건수"]} for r in rows],
            "사용처 상위 10": top_rows,
        }
    ),
    file_name=f"가계부-{period.start}_{period.end}.xlsx",
    icon=":material/download:",
)
