"""사용처(가맹점) 이름 정규화와 규칙 기반 자동 분류.

가맹점명은 같은 가게라도 "스타벅스 강남역점", "(주)스타벅스코리아", "STARBUCKS" 처럼 제각각이다.
비교 전에 회사 표기·결제대행 접두어·지점명을 걷어내고 대문자·공백 없는 형태로 맞춘다.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Callable

from .default_rules import DEFAULT_RULES

COMPANY_MARKS = re.compile(r"\(주\)|㈜|\(유\)|\(사\)|주식회사|유한회사|\(株\)|co\.?,?\s*ltd\.?|inc\.?|corp\.?", re.I)
# 결제대행사·간편결제 접두어 (예: "KCP_쿠팡", "NICE*넷플릭스", "네이버페이-무신사")
PG_PREFIX = re.compile(
    r"^(kcp|nice|kicc|ksnet|inicis|이니시스|토스페이먼츠|toss|다날|danal|네이버페이|naverpay|카카오페이|kakaopay|페이코|payco|smilepay|스마일페이|paypal)\s*[_*\-:/]\s*",
    re.I,
)
# 마지막 단어가 지점명이면 뗀다 (예: "강남역점", "본점", "2호점")
BRANCH_SUFFIX = re.compile(r"\s+\S*(점|지점|매장|센터점|직영점)$")
PUNCT = re.compile(r"[\s.,·_\-*()\[\]/\\'\"`~!@#$%^&+=|:;<>?]")


def base_merchant_name(merchant: str) -> str:
    """표시용으로 정리한 사용처 이름. 예: "스타벅스 강남역점" → "스타벅스" """
    name = unicodedata.normalize("NFC", merchant)
    name = re.sub(r"\s+", " ", COMPANY_MARKS.sub(" ", name)).strip()
    name = PG_PREFIX.sub("", name, count=1)
    without_branch = BRANCH_SUFFIX.sub("", name, count=1)
    if len(without_branch.strip()) >= 2:
        name = without_branch
    return name.strip() or merchant.strip()


def normalize_merchant(merchant: str) -> str:
    """비교용 키: 대문자, 공백·구두점 제거. 예: "Starbucks 강남역점" → "STARBUCKS" """
    return PUNCT.sub("", base_merchant_name(merchant).upper())


def _dictionary() -> list[tuple[str, str]]:
    entries = [(normalize_merchant(k), cat) for cat, kws in DEFAULT_RULES.items() for k in kws]
    return sorted([e for e in entries if e[0]], key=lambda e: -len(e[0]))


DICTIONARY = _dictionary()


def _is_short_latin(k: str) -> bool:
    return len(k) <= 3 and re.fullmatch(r"[A-Z0-9]+", k) is not None


def contains_keyword(name: str, keyword: str) -> bool:
    """"KT" 같은 짧은 영문 키워드가 "KTX" 에 걸리지 않도록, 3자 이하 영문·숫자 키워드는 단어 단위로만 맞춘다."""
    if not keyword:
        return False
    if not _is_short_latin(keyword):
        return keyword in name
    return re.search(rf"(^|[^A-Z0-9]){re.escape(keyword)}($|[^A-Z0-9])", name) is not None


def create_classifier(rules: list[dict], categories: list[dict]) -> Callable[[str], str | None]:
    """분류기(사용처 → 항목 id | None). 순서: 사용자 규칙(priority 높은 순, equals 먼저) → 기본 사전 → 미분류.

    기본 사전은 항목 "이름"으로 맞추므로, 사용자가 지우거나 이름을 바꾼 기본 항목은 건너뛴다.
    """
    prepared = [dict(r, key=normalize_merchant(r["keyword"])) for r in rules]
    prepared = [r for r in prepared if r["key"]]
    prepared.sort(key=lambda r: (-int(r.get("priority") or 0), -int(r["match_type"] == "equals"), -len(r["key"])))
    id_by_name = {c["name"]: c["id"] for c in categories}
    valid_ids = {c["id"] for c in categories}

    def classify(merchant: str) -> str | None:
        name = normalize_merchant(merchant)
        raw_name = re.sub(r"\s+", "", merchant.upper())  # 지점명 제거로 키워드가 잘리는 경우 대비
        if not name:
            return None
        for r in prepared:
            if r["category_id"] not in valid_ids:
                continue
            hit = name == r["key"] if r["match_type"] == "equals" else contains_keyword(name, r["key"]) or contains_keyword(raw_name, r["key"])
            if hit:
                return r["category_id"]
        for keyword, cat_name in DICTIONARY:
            if contains_keyword(name, keyword) or contains_keyword(raw_name, keyword):
                cid = id_by_name.get(cat_name)
                if cid:
                    return cid
        return None

    return classify


def rule_matches(rule: dict, merchant: str) -> bool:
    """규칙 하나가 이 사용처에 맞는지. 규칙을 저장한 뒤 기존 거래에 바로 적용할 때 쓴다."""
    key = normalize_merchant(rule["keyword"])
    name = normalize_merchant(merchant)
    if not key or not name:
        return False
    return name == key if rule["match_type"] == "equals" else contains_keyword(name, key)
