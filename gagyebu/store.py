"""가계부 데이터(항목·거래·규칙·열 매핑 양식·업로드 이력)와 그 조작.

데이터는 서버에 저장하지 않는다. Streamlit 세션에만 두고, 사용자가 백업 파일(JSON)로 내려받아 다음에 다시 불러온다.
백업 형식은 Next.js 판의 로컬판 데이터 파일(gagyebu-data.json)과 같아서 서로 옮겨 쓸 수 있다.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from .classify import rule_matches

TABLES = ("categories", "transactions", "rules", "column_presets", "import_batches")
ETC = "기타"
DEFAULT_CATEGORIES = [
    ("식비", "#ef4444"), ("카페·간식", "#f97316"), ("교통", "#eab308"), ("주거·관리비", "#84cc16"),
    ("통신", "#14b8a6"), ("쇼핑", "#06b6d4"), ("의료", "#3b82f6"), ("교육", "#6366f1"),
    ("문화·여가", "#a855f7"), ("구독", "#ec4899"), ("기타", "#9ca3af"),
]  # fmt: skip


class StoreError(ValueError):
    """사용자에게 그대로 보여 줄 수 있는 오류"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id() -> str:
    return str(uuid.uuid4())


def new_store() -> dict:
    return {
        "categories": [
            {"id": _id(), "name": n, "color": c, "parent_id": None, "monthly_budget": None, "sort_order": i + 1, "created_at": _now()}
            for i, (n, c) in enumerate(DEFAULT_CATEGORIES)
        ],
        "transactions": [],
        "rules": [],
        "column_presets": [],
        "import_batches": [],
    }


# 백업 ------------------------------------------------------------------------------


def dump_backup(data: dict) -> bytes:
    payload = {"version": 1, "savedAt": _now(), **{t: data[t] for t in TABLES}}
    return json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8")


def load_backup(raw: bytes) -> dict:
    try:
        saved = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise StoreError(f"백업 파일을 읽지 못했습니다: {e}") from e
    if not isinstance(saved, dict) or not isinstance(saved.get("categories"), list):
        raise StoreError("가계부 백업 파일(JSON)이 아닙니다.")
    data = {t: [dict(r) for r in saved.get(t, []) if isinstance(r, dict)] for t in TABLES}
    for t in data["transactions"]:
        if not isinstance(t.get("amount"), int) or not isinstance(t.get("date"), str) or not isinstance(t.get("merchant"), str):
            raise StoreError("백업 파일의 거래 형식이 올바르지 않습니다.")
    if not any(c.get("name") == ETC and not c.get("parent_id") for c in data["categories"]):
        data["categories"].append({"id": _id(), "name": ETC, "color": "#9ca3af", "parent_id": None, "monthly_budget": None, "sort_order": 99, "created_at": _now()})
    return data


# 항목 ------------------------------------------------------------------------------


def ordered_categories(data: dict) -> list[tuple[dict, int]]:
    """상위 항목 아래에 하위 항목을 들여 쓴 순서 [(항목, 깊이)]"""
    cats = sorted(data["categories"], key=lambda c: (c.get("sort_order") or 0, c["name"]))
    out = []
    for parent in (c for c in cats if not c.get("parent_id")):
        out.append((parent, 0))
        out.extend((c, 1) for c in cats if c.get("parent_id") == parent["id"])
    return out


def category_label(data: dict, cid: str | None) -> str:
    """"상위 > 하위" 표시 이름. 없으면 "미분류" """
    by_id = {c["id"]: c for c in data["categories"]}
    c = by_id.get(cid) if cid else None
    if not c:
        return "미분류"
    parent = by_id.get(c.get("parent_id"))
    return f"{parent['name']} > {c['name']}" if parent else c["name"]


def category_color(data: dict, cid: str | None) -> str:
    c = next((x for x in data["categories"] if x["id"] == cid), None)
    return c["color"] if c else "#d1d5db"


def etc_id(data: dict) -> str:
    return next(c["id"] for c in data["categories"] if c["name"] == ETC and not c.get("parent_id"))


def add_category(data: dict, name: str, color: str = "#64748b", parent_id: str | None = None, monthly_budget: int | None = None) -> dict:
    name = name.strip()
    if not name:
        raise StoreError("항목 이름을 입력해 주세요.")
    if any(c["name"] == name and c.get("parent_id") == parent_id for c in data["categories"]):
        raise StoreError(f"'{name}' 항목이 이미 있습니다.")
    cat = {
        "id": _id(), "name": name, "color": color, "parent_id": parent_id, "monthly_budget": monthly_budget,
        "sort_order": max((c.get("sort_order") or 0 for c in data["categories"]), default=0) + 1, "created_at": _now(),
    }  # fmt: skip
    data["categories"].append(cat)
    return cat


def update_category(data: dict, cid: str, **patch) -> None:
    cat = next(c for c in data["categories"] if c["id"] == cid)
    if "name" in patch:
        name = patch["name"].strip()
        if not name:
            raise StoreError("항목 이름을 입력해 주세요.")
        if cat["name"] == ETC and not cat.get("parent_id") and name != ETC:
            raise StoreError("'기타' 항목은 이름을 바꿀 수 없습니다.")
        if any(c["id"] != cid and c["name"] == name and c.get("parent_id") == cat.get("parent_id") for c in data["categories"]):
            raise StoreError(f"'{name}' 항목이 이미 있습니다.")
        patch["name"] = name
    cat.update(patch)


def delete_category(data: dict, cid: str) -> None:
    """소속 거래는 '기타'로 옮기고 지운다. 하위 항목과 규칙도 함께 지우며, 하위 항목의 거래는 미분류가 된다."""
    etc = etc_id(data)
    if cid == etc:
        raise StoreError("'기타' 항목은 지울 수 없습니다.")
    for t in data["transactions"]:
        if t.get("category_id") == cid:
            t["category_id"] = etc
    ids = {cid} | {c["id"] for c in data["categories"] if c.get("parent_id") == cid}
    for t in data["transactions"]:
        if t.get("category_id") in ids:
            t["category_id"] = None
    data["rules"] = [r for r in data["rules"] if r["category_id"] not in ids]
    data["categories"] = [c for c in data["categories"] if c["id"] not in ids]


# 거래 ------------------------------------------------------------------------------


def filter_transactions(data: dict, start: str | None = None, end: str | None = None, category: str | None | object = ..., search: str = "") -> list[dict]:
    """날짜 내림차순. category=None 이면 미분류만, ... 이면 전체."""
    term = search.strip().lower()
    out = []
    for t in data["transactions"]:
        if start and t["date"] < start or end and t["date"] > end:
            continue
        if category is not ... and t.get("category_id") != category:
            continue
        if term and term not in t["merchant"].lower() and term not in (t.get("memo") or "").lower():
            continue
        out.append(t)
    return sorted(out, key=lambda t: (t["date"], t.get("time") or ""), reverse=True)


def set_category(data: dict, tx_ids: set[str], category_id: str | None, by: str = "manual") -> int:
    n = 0
    for t in data["transactions"]:
        if t["id"] in tx_ids:
            t["category_id"] = category_id
            t["classified_by"] = by if category_id else None
            n += 1
    return n


def import_rows(data: dict, file_name: str, source_preset: str | None, rows: list[dict], classify) -> dict:
    """한 번의 업로드(배치) + 거래들을 추가한다. 업로드 시점에 자동 분류한다."""
    batch = {"id": _id(), "file_name": file_name, "source_preset": source_preset, "row_count": len(rows), "imported_at": _now()}
    data["import_batches"].append(batch)
    for r in rows:
        cid = classify(r["merchant"])
        data["transactions"].append(
            {"id": _id(), "batch_id": batch["id"], **r, "category_id": cid, "classified_by": "rule" if cid else None, "created_at": _now()}
        )
    return batch


def delete_batch(data: dict, batch_id: str) -> int:
    before = len(data["transactions"])
    data["transactions"] = [t for t in data["transactions"] if t.get("batch_id") != batch_id]
    data["import_batches"] = [b for b in data["import_batches"] if b["id"] != batch_id]
    return before - len(data["transactions"])


# 규칙 ------------------------------------------------------------------------------


def upsert_rule(data: dict, keyword: str, category_id: str, match_type: str = "contains", priority: int = 0) -> dict:
    keyword = keyword.strip()
    if not keyword:
        raise StoreError("키워드를 입력해 주세요.")
    rule = next((r for r in data["rules"] if r["match_type"] == match_type and r["keyword"] == keyword), None)
    if rule:
        rule.update(category_id=category_id, priority=priority)
    else:
        rule = {"id": _id(), "match_type": match_type, "keyword": keyword, "category_id": category_id, "priority": priority, "created_at": _now()}
        data["rules"].append(rule)
    return rule


def apply_rule(data: dict, rule: dict, by: str = "rule") -> int:
    """규칙을 수동 분류가 아닌 기존 거래 전체에 다시 적용한다. 바뀐 건수를 돌려준다."""
    ids = {
        t["id"]
        for t in data["transactions"]
        if t.get("classified_by") != "manual" and t.get("category_id") != rule["category_id"] and rule_matches(rule, t["merchant"])
    }
    return set_category(data, ids, rule["category_id"], by)


def ordered_rules(data: dict) -> list[dict]:
    return sorted(data["rules"], key=lambda r: (-(r.get("priority") or 0), r.get("created_at") or ""))


# 열 매핑 양식 ------------------------------------------------------------------------


def save_preset(data: dict, name: str, mapping: dict) -> dict:
    name = name.strip() or "이름 없는 양식"
    preset = next((p for p in data["column_presets"] if p["name"] == name), None)
    if preset:
        preset["mapping"] = mapping
    else:
        preset = {"id": _id(), "name": name, "mapping": mapping, "created_at": _now()}
        data["column_presets"].append(preset)
    return preset
