"""집계·거래 목록을 .xlsx 로 만든다(내려받기 버튼용)."""

from __future__ import annotations

import io

import pandas as pd


def workbook_bytes(sheets: dict[str, list[dict]]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, rows in sheets.items():
            df = pd.DataFrame(rows if rows else [{"내용": "데이터 없음"}])
            df.to_excel(writer, sheet_name=name[:31], index=False)  # 시트 이름은 31자까지
    return buf.getvalue()
