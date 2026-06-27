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


MAX_POSTS_TO_CLAUDE = 300

def find_related(posts: list, keyword: str, top_n: int = 5) -> list:
    client = _get_client()
    posts = posts[:MAX_POSTS_TO_CLAUDE]
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
        model="claude-haiku-4-5-20251001",
        max_tokens=8192,
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
    """새 글 키워드와 유사한 기존 글을 찾아 중복 여부 판단 (로컬 처리, API 호출 없음)."""
    from difflib import SequenceMatcher

    kw = keyword.lower()
    kw_words = set(kw.split())

    scored = []
    for p in posts:
        title = p["title"].lower()

        # 1) 시퀀스 유사도 (전체 문자열)
        seq_score = SequenceMatcher(None, kw, title).ratio()

        # 2) 키워드 단어 포함 비율
        title_words = set(title.split())
        if kw_words:
            word_score = len(kw_words & title_words) / len(kw_words)
        else:
            word_score = 0.0

        # 3) 키워드 통째로 포함 여부 (substring)
        exact_bonus = 0.3 if kw in title else 0.0

        combined = min(1.0, seq_score * 0.4 + word_score * 0.4 + exact_bonus)
        similarity = round(combined * 100)

        if similarity >= 20:
            scored.append({
                "title": p["title"],
                "url": p["url"],
                "date": p.get("date", ""),
                "similarity": similarity,
                "overlap": f"'{keyword}' 관련 내용 포함",
            })

    scored.sort(key=lambda x: x["similarity"], reverse=True)
    similar_posts = scored[:top_n]

    return {
        "has_duplicate": len(similar_posts) > 0,
        "similar_posts": similar_posts,
    }
