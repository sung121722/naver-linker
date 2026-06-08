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
        f"{i+1}. [{p.get('date', '')}] {p['title']} | {p['url']}" for i, p in enumerate(posts)
    )

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
                                },
                                "score": {
                                    "type": "integer",
                                    "description": "새 글과의 관련도 점수 (0~100). 키워드 직접 일치=90이상, 주제 유사=60~89, 약한 연관=40~59",
                                    "minimum": 0,
                                    "maximum": 100
                                }
                            },
                            "required": ["title", "url", "reason", "score"]
                        }
                    }
                },
                "required": ["recommendations"]
            }
        }
    ]

    # 글 목록(post_list)은 캐싱, 키워드 지시문은 매번 새로 전송
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=4096,
        tools=tools,
        tool_choice={"type": "any"},
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": f"아래는 네이버 블로그의 전체 글 목록입니다 (번호. [작성일] 제목 | URL 형식):\n\n{post_list}",
                    "cache_control": {"type": "ephemeral"}
                },
                {
                    "type": "text",
                    "text": f'\n\n새 글의 주제/키워드: "{keyword}"\n\n위 목록에서 새 글과 관련도가 높아 내부 링크로 연결하기 좋은 글을 {top_n}개 골라주세요.\n관련도가 비슷한 경우 최근 작성된 글을 우선 선택해주세요.'
                }
            ]
        }],
    )

    date_map = {p["url"]: p.get("date", "") for p in posts}

    for block in response.content:
        if block.type == "tool_use" and block.name == "recommend_posts":
            results = block.input.get("recommendations", [])
            for r in results:
                r["date"] = date_map.get(r.get("url", ""), "")
            return results

    return []


def find_duplicates(posts: list, keyword: str, top_n: int = 10) -> dict:
    """새 글 키워드와 유사한 기존 글을 찾아 중복 여부 판단"""
    client = _get_client()
    post_list = "\n".join(
        f"{i+1}. {p['title']} | {p['url']} | {p.get('date','날짜미상')}" for i, p in enumerate(posts)
    )

    prompt = f"""아래는 네이버 블로그의 기존 글 목록입니다 (번호. 제목 | URL | 작성일 형식):

{post_list}

새로 쓰려는 글의 키워드/주제: "{keyword}"

위 기존 글 중에서 새 글과 주제가 겹치거나 비슷한 글을 찾아주세요.
유사도가 높은 순서대로 최대 {top_n}개까지만 반환하세요.
유사한 글이 전혀 없으면 빈 배열을 반환하세요."""

    tools = [
        {
            "name": "check_duplicates",
            "description": "새 글과 유사한 기존 글 목록을 반환합니다",
            "input_schema": {
                "type": "object",
                "properties": {
                    "has_duplicate": {
                        "type": "boolean",
                        "description": "유사한 글이 1개 이상 존재하면 true"
                    },
                    "similar_posts": {
                        "type": "array",
                        "description": "유사도 높은 기존 글 목록 (최대 5개, 없으면 빈 배열)",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string", "description": "기존 글 제목"},
                                "url": {"type": "string", "description": "기존 글 URL"},
                                "date": {"type": "string", "description": "기존 글 작성일 (원문 그대로)"},
                                "similarity": {
                                    "type": "integer",
                                    "description": "유사도 (0~100 사이 정수)",
                                    "minimum": 0,
                                    "maximum": 100
                                },
                                "overlap": {"type": "string", "description": "겹치는 내용 한 줄 요약"}
                            },
                            "required": ["title", "url", "date", "similarity", "overlap"]
                        }
                    }
                },
                "required": ["has_duplicate", "similar_posts"]
            }
        }
    ]

    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=2048,
        tools=tools,
        tool_choice={"type": "any"},
        messages=[{"role": "user", "content": prompt}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "check_duplicates":
            return block.input

    return {"has_duplicate": False, "similar_posts": []}
