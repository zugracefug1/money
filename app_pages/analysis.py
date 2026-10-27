"""분석: 월간 요약, 12개월 추이, 전월 대비 증감, 요일·시간대, 고정지출, 이상 지출."""

import altair as alt
import pandas as pd
import streamlit as st

from gagyebu import ui
from gagyebu.analysis import (
    UNCATEGORIZED,
    WEEKDAYS,
    compare_months,
    detect_recurring,
    find_anomalies,
    last_months,
    monthly_series,
    monthly_summary,
    weekday_hour_grid,
)
from gagyebu.period import add_months, month_label, month_of

st.title("분석")
d = ui.data()
if not d["transactions"]:
    st.info("아직 거래가 없습니다. 업로드 화면에서 엑셀을 올려 주세요.", icon=":material/info:")
    st.stop()

months = sorted({month_of(t["date"]) for t in d["transactions"]}, reverse=True)
ym = st.selectbox("기준 월", months, format_func=month_label, key="analysis_month")
txs = d["transactions"]


def name_of(key: str) -> str:
    return ui.label(None if key == UNCATEGORIZED else key)


current_txs = [t for t in txs if month_of(t["date"]) == ym]
prev_txs = [t for t in txs if month_of(t["date"]) == add_months(ym, -1)]
changes = compare_months(txs, ym)
recurring = detect_recurring(txs, ym)

# 월간 요약 -------------------------------------------------------------------------------
summary = monthly_summary(
    month_label(ym),
    sum(t["amount"] for t in current_txs),
    sum(t["amount"] for t in prev_txs) if prev_txs else None,
    changes,
    name_of,
    sum(r["amount"] for r in recurring),
)
st.info("\n".join(f"- {s}" for s in summary), icon=":material/summarize:")

# 12개월 추이 ------------------------------------------------------------------------------
st.subheader("최근 12개월 지출 추이")
cat_keys = sorted({t.get("category_id") or UNCATEGORIZED for t in txs}, key=name_of)
picked = st.multiselect("항목별 선 겹쳐 보기 (최대 5개)", cat_keys, format_func=name_of, max_selections=5, key="trend_cats", placeholder="항목 선택")
series = monthly_series(txs, ym, 12, picked)
lines = [("총지출", [p["total"] for p in series])] + [(name_of(k), [p["by_category"][k] for p in series]) for k in picked]
rows = []
for name, values in lines:
    segment = 0  # 거래가 없는 달(None)에서 선을 끊는다
    for p, v in zip(series, values, strict=True):
        if v is None:
            segment += 1
            continue
        rows.append({"월": p["month"], "구분": name, "금액": v, "조각": f"{name}-{segment}"})
tdf = pd.DataFrame(rows)
if not tdf.empty:
    # 거래가 없는 달도 축에 남겨 12개월이 모두 보이게 한다
    x = alt.X("월:O", scale=alt.Scale(domain=last_months(ym, 12)), title=None, axis=alt.Axis(labelAngle=0, labelExpr="slice(datum.value, 2)"))
    chart = (
        alt.Chart(tdf)
        .mark_line(point=True)
        .encode(x=x, y=alt.Y("금액:Q", title=None, axis=alt.Axis(format="~s")), color=alt.Color("구분:N", legend=alt.Legend(title=None, orient="bottom")), detail="조각:N",
                strokeDash=alt.condition(alt.datum["구분"] == "총지출", alt.value([1, 0]), alt.value([4, 3])),
                tooltip=["월:O", "구분:N", alt.Tooltip("금액:Q", format=",")])
    )  # fmt: skip
    st.altair_chart(chart.properties(height=300), alt="최근 12개월 월별 지출 선 차트")
    st.caption("거래가 없는 달은 0이 아니라 빈 칸으로 둡니다.")

# 전월 대비 --------------------------------------------------------------------------------
st.subheader(f"{month_label(ym)} vs {month_label(add_months(ym, -1))}")
if changes:
    cdf = pd.DataFrame(
        [
            {"항목": name_of(c["key"]), "이번 달": c["current"], "지난달": c["previous"], "증감": c["diff"], "증감률": c["rate"], "": "크게 늘었음" if c["highlight"] else ""}
            for c in changes
        ]
    )

    def _hl(row):
        return ["background-color: #f9eeda; font-weight: 600" if row[""] else ""] * len(row)

    st.dataframe(
        cdf.style.apply(_hl, axis=1),
        hide_index=True,
        column_config={
            "이번 달": st.column_config.NumberColumn("이번 달(원)", format="localized"),
            "지난달": st.column_config.NumberColumn("지난달(원)", format="localized"),
            "증감": st.column_config.NumberColumn("증감(원)", format="localized"),
            "증감률": st.column_config.NumberColumn(format="percent"),
            "": st.column_config.TextColumn("강조", help="20% 이상 그리고 5만원 이상 늘어난 항목"),
        },
    )

# 요일·시간대 ------------------------------------------------------------------------------
st.subheader("요일·시간대별 지출")
grid = weekday_hour_grid(current_txs)
if grid["has_time"]:
    hdf = pd.DataFrame([{"요일": WEEKDAYS[w], "시": h, "금액": grid["grid"][w][h]} for w in range(7) for h in range(24)])
    heat = (
        alt.Chart(hdf)
        .mark_rect()
        .encode(x=alt.X("시:O", title="시"), y=alt.Y("요일:O", sort=WEEKDAYS, title=None), color=alt.Color("금액:Q", scale=alt.Scale(scheme="oranges"), legend=alt.Legend(format="~s", title="금액")),
                tooltip=["요일:O", alt.Tooltip("시:O", title="시"), alt.Tooltip("금액:Q", format=",")])
    )  # fmt: skip
    st.altair_chart(heat.properties(height=240), alt="요일×시간대 지출 히트맵")
    if grid["timed_count"] < sum(1 for t in current_txs if t["amount"] > 0):
        st.caption("시간 정보가 없는 거래는 히트맵에서 빠지고 요일별 합계에만 들어갑니다.")
else:
    st.caption("시간 정보가 있는 양식을 올리면 시간대별 히트맵을 볼 수 있어요. 지금은 요일별 합계만 보여 줍니다.")
wdf = pd.DataFrame([{"요일": WEEKDAYS[i], "금액": v} for i, v in enumerate(grid["weekday_totals"])])
st.altair_chart(
    alt.Chart(wdf).mark_bar().encode(x=alt.X("요일:O", sort=WEEKDAYS, title=None, axis=alt.Axis(labelAngle=0)), y=alt.Y("금액:Q", title=None, axis=alt.Axis(format="~s")), tooltip=["요일:O", alt.Tooltip("금액:Q", format=",")]).properties(height=200),
    alt="요일별 지출 막대 차트",
)

# 고정지출 ---------------------------------------------------------------------------------
st.subheader("고정지출")
if recurring:
    st.caption(f"3개월 이상 비슷한 날짜·금액으로 반복된 결제 · 월 합계 약 {ui.won(sum(r['amount'] for r in recurring))}")
    st.dataframe(
        pd.DataFrame([{"사용처": r["name"], "항목": ui.label(r["category_id"]), "금액": r["amount"], "결제일": f"매월 {r['day']}일경", "연속": f"{len(r['months'])}개월"} for r in recurring]),
        hide_index=True,
        column_config={"금액": st.column_config.NumberColumn("금액(원)", format="localized")},
    )
else:
    st.caption("3개월 이상 같은 날짜·금액으로 반복된 결제가 없습니다.")

# 이상 지출 --------------------------------------------------------------------------------
st.subheader("이상 지출")
anomalies = find_anomalies(txs, ym)
if anomalies["transactions"] or anomalies["categories"]:
    if anomalies["transactions"]:
        st.markdown("**평소보다 큰 거래** (그 항목의 최근 3개월 건당 평균의 2배 초과)")
        st.dataframe(
            pd.DataFrame([{"날짜": a["tx"]["date"], "사용처": a["tx"]["merchant"], "항목": ui.label(a["tx"].get("category_id")), "금액": a["tx"]["amount"], "평균": round(a["average"]), "배수": f"{a['ratio']:.1f}배"} for a in anomalies["transactions"]]),
            hide_index=True,
            column_config={"금액": st.column_config.NumberColumn("금액(원)", format="localized"), "평균": st.column_config.NumberColumn("건당 평균(원)", format="localized")},
        )
    if anomalies["categories"]:
        st.markdown("**평소보다 많이 쓴 항목** (최근 3개월 월평균의 2배 초과)")
        st.dataframe(
            pd.DataFrame([{"항목": name_of(a["key"]), "이번 달": a["total"], "월평균": round(a["average"]), "배수": f"{a['ratio']:.1f}배"} for a in anomalies["categories"]]),
            hide_index=True,
            column_config={"이번 달": st.column_config.NumberColumn("이번 달(원)", format="localized"), "월평균": st.column_config.NumberColumn("월평균(원)", format="localized")},
        )
else:
    st.caption("최근 3개월과 비교해 눈에 띄게 큰 지출이 없습니다.")
