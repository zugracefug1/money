"""분류 테스트. Next.js 판 lib/classify/*.test.ts 와 같은 기대값을 쓴다."""

from pathlib import Path

import pytest

from gagyebu.classify import base_merchant_name, create_classifier, normalize_merchant, rule_matches
from gagyebu.default_rules import DEFAULT_RULES
from gagyebu.importer import build_rows, find_header_row, find_sensitive_columns, guess_mapping, read_workbook

NAMES = ["식비", "카페·간식", "교통", "주거·관리비", "통신", "쇼핑", "의료", "교육", "문화·여가", "구독", "기타"]
CATS = [{"id": f"c{i}", "name": n} for i, n in enumerate(NAMES)]
ID = {c["name"]: c["id"] for c in CATS}
NAME = {c["id"]: c["name"] for c in CATS}


@pytest.mark.parametrize(
    "text,expected",
    [
        ("스타벅스 강남역점", "스타벅스"), ("(주)스타벅스코리아", "스타벅스코리아"), ("㈜ 이마트 성수점", "이마트"),
        ("KCP_쿠팡", "쿠팡"), ("NICE*넷플릭스", "넷플릭스"), ("netflix.com", "NETFLIXCOM"), ("본점", "본점"),
    ],
)  # fmt: skip
def test_normalize_merchant(text, expected):
    assert normalize_merchant(text) == expected


def test_base_merchant_name_keeps_case_and_spaces():
    assert base_merchant_name("스타벅스 강남역점") == "스타벅스"
    assert base_merchant_name("CGV 용산아이파크몰점") == "CGV"


@pytest.mark.parametrize(
    "merchant,expected",
    [
        ("스타벅스 강남역점", "카페·간식"), ("배달의민족", "식비"), ("쿠팡이츠", "식비"), ("쿠팡", "쇼핑"), ("카카오T 택시", "교통"),
        ("SKT 통신요금", "통신"), ("KT 인터넷", "통신"), ("넷플릭스", "구독"), ("유튜브프리미엄", "구독"), ("GS25 역삼점", "카페·간식"),
        ("CGV 용산", "문화·여가"), ("올리브영", "쇼핑"), ("AMAZON.COM", "쇼핑"), ("교보문고", "교육"), ("관리비", "주거·관리비"),
        ("서울내과의원", "의료"),
    ],
)  # fmt: skip
def test_default_dictionary(merchant, expected):
    assert NAME.get(create_classifier([], CATS)(merchant)) == expected


def test_dictionary_edge_cases():
    classify = create_classifier([], CATS)
    assert NAME.get(classify("KTX 승차권")) != "통신"
    assert classify("홍길동상회") is None
    assert create_classifier([], [c for c in CATS if c["name"] != "구독"])("넷플릭스") is None


def test_user_rules_order():
    rule = lambda kw, cat, mt="contains", p=0: {"match_type": mt, "keyword": kw, "category_id": ID[cat], "priority": p}
    assert NAME[create_classifier([rule("스타벅스", "식비")], CATS)("스타벅스 역삼점")] == "식비"
    classify = create_classifier([rule("마트", "쇼핑"), rule("동네마트", "식비", "equals"), rule("동네", "기타", p=5)], CATS)
    assert NAME[classify("동네마트")] == "기타"
    assert NAME[classify("우리마트")] == "쇼핑"
    deleted = [{"match_type": "contains", "keyword": "넷플릭스", "category_id": "deleted", "priority": 9}]
    assert NAME[create_classifier(deleted, CATS)("넷플릭스")] == "구독"


def test_rule_matches_ignores_branch():
    assert rule_matches({"match_type": "contains", "keyword": "스타벅스"}, "스타벅스 강남역점")
    assert not rule_matches({"match_type": "contains", "keyword": "스타벅스"}, "이디야")
    assert rule_matches({"match_type": "equals", "keyword": "스타벅스"}, "스타벅스 강남역점")


def test_sample_classification_rate_at_least_70_percent():
    classify = create_classifier([], [{"id": str(i), "name": n} for i, n in enumerate(DEFAULT_RULES)])
    total = hit = 0
    for f in sorted((Path(__file__).resolve().parent.parent / "samples").glob("*")):
        table = read_workbook(f.read_bytes(), f.name)
        hi = find_header_row(table.rows)
        mapping = guess_mapping(table.rows[hi], find_sensitive_columns(table.rows[hi], table.rows[hi + 1 :]))
        for r in build_rows(table, hi, mapping)[0]:
            if r.status == "ok":
                total += 1
                hit += classify(r.tx["merchant"]) is not None
    assert total > 0 and hit / total >= 0.7
