import os
from pathlib import Path
from anthropic import Anthropic


def _get_client() -> Anthropic:
    env = Path(__file__).parent / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                key = line.split("=", 1)[1].strip()
                if key:
                    return Anthropic(api_key=key)
    # Railway/Render 환경변수에서 자동 읽기
    return Anthropic()


def find_related(posts: list, keyword: str, top_n: int = 5) -> list:
    client = _get_client()
    post_list = "\n".join(
        f"{i+1}. {p['title']} | {p['url']}" for i, p in enumerate(posts)
    )

    prompt = f"""아래는 네이버 블로그의 전체 글 목록입니다 (번호. 제목 | URL 형식):

{post_list}

새 글의 주제/키워드: "{keyword}"

위 목록에서 새 글과 관련도가 높아 내부 링크로 연결하기 좋은 글을 {top_n}개 골라주세요."""

    tools = [
        {
            "name": "recommend_posts",
            "description": "관련 글 추천 결과를 반환합니다",
            "input_schema": {
                "type": "object",
                "properties": {
                    "recommendations": {
                        "type": "array",
                        "description": f"관련도 높은 글 {top_n}개",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {
                                    "type": "string",
                                    "description": "글 제목 (원문 그대로)"
                                },
                                "url": {
                                    "type": "string",
                                    "description": "글 URL (원문 그대로)"
                                },
                                "reason": {
                                    "type": "string",
                                    "description": "이 글을 추천하는 이유 한 줄"
                                }
                            },
                            "required": ["title", "url", "reason"]
                        }
                    }
                },
                "required": ["recommendations"]
            }
        }
    ]

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        tools=tools,
        tool_choice={"type": "any"},  # 반드시 tool 사용 강제
        messages=[{"role": "user", "content": prompt}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "recommend_posts":
            return block.input.get("recommendations", [])

    return []
