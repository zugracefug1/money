"""미분류 사용처에 Claude 로 항목을 추천한다(선택 기능).

API 키는 Streamlit secrets(ANTHROPIC_API_KEY) 또는 환경변수로만 받는다.
보내는 정보는 사용처 이름과 사용자의 항목 이름뿐이다. 금액·날짜는 보내지 않으며, 추천은 사용자가 수락해야 저장된다.
"""

from __future__ import annotations

import json
import os

AI_MODEL = "claude-haiku-5-5"
AI_MAX_MERCHANTS = 50

SYSTEM = (
    "당신은 한국 가계부 앱의 거래 분류기입니다. 카드·은행 거래내역의 가맹점(사용처) 이름을 보고 "
    "사용자가 정한 지출 항목 중 가장 알맞은 하나를 고릅니다. 가맹점 이름만으로 판단하기 어려우면 category 를 null 로 둡니다. "
    "입력의 모든 사용처에 대해 결과를 하나씩, 입력에 적힌 이름 그대로 돌려줍니다."
)


class AiError(RuntimeError):
    pass


def api_key() -> str | None:
    try:
        import streamlit as st

        key = st.secrets.get("ANTHROPIC_API_KEY")
        if key:
            return str(key)
    except Exception:  # secrets.toml 이 없으면 예외가 난다
        pass
    return os.environ.get("ANTHROPIC_API_KEY") or None


def is_configured() -> bool:
    return api_key() is not None


def suggest_categories(merchants: list[str], category_names: list[str]) -> list[dict]:
    """[{merchant, category}] — 입력에 있던 사용처와 항목 이름으로 걸러 낸 추천만 돌려준다."""
    key = api_key()
    if not key:
        raise AiError("AI 분류가 설정되지 않았습니다(ANTHROPIC_API_KEY).")
    if not merchants or not category_names:
        return []

    import anthropic

    schema = {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "merchant": {"type": "string"},
                        "category": {"anyOf": [{"type": "string", "enum": category_names}, {"type": "null"}]},
                    },
                    "required": ["merchant", "category"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["results"],
        "additionalProperties": False,
    }
    content = "항목 목록:\n" + "\n".join(f"- {n}" for n in category_names) + "\n\n분류할 사용처:\n" + "\n".join(f"- {m}" for m in merchants)

    client = anthropic.Anthropic(api_key=key)
    try:
        response = client.messages.create(
            model=AI_MODEL,
            max_tokens=8000,
            system=SYSTEM,
            messages=[{"role": "user", "content": content}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        )
    except anthropic.RateLimitError as e:
        raise AiError("AI 요청이 많아 잠시 후 다시 시도해 주세요.") from e
    except anthropic.AuthenticationError as e:
        raise AiError("AI API 키가 올바르지 않습니다.") from e
    except anthropic.APIError as e:
        raise AiError("AI 분류 요청에 실패했습니다.") from e

    if response.stop_reason == "refusal":
        raise AiError("AI가 이 요청을 처리하지 않았습니다.")
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        results = json.loads(text)["results"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise AiError("AI 응답을 해석하지 못했습니다.") from e

    wanted, names = set(merchants), set(category_names)
    return [r for r in results if r.get("merchant") in wanted and r.get("category") in names]
