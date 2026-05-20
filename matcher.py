import json
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
    # Railway 환경변수에서 자동 읽기
    return Anthropic()


def find_related(posts: list, keyword: str, top_n: int = 5) -> list:
    client = _get_client()
    post_list = "\n".join(
        f"{i+1}. {p['title']} | {p['url']}" for i, p in enumerate(posts)
    )

    prompt = f"""아래는 네이버 블로그의 전체 글 목록입니다 (번호. 제목 | URL 형식):

{post_list}

새 글의 주제/키워드: "{keyword}"

위 목록에서 새 글과 관련도가 높아 내부 링크로 연결하기 좋은 글을 {top_n}개 골라주세요.

반드시 아래 JSON 형식으로만 답하세요. 다른 설명은 하지 마세요:
[
  {{"title": "글 제목", "url": "https://...", "reason": "연결 이유 한 줄"}},
  ...
]"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()

    # 코드블록 제거
    if "```" in raw:
        parts = raw.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("["):
                raw = part
                break

    # JSON 배열 부분만 추출
    start = raw.find("[")
    end = raw.rfind("]")
    if start != -1 and end != -1:
        raw = raw[start:end+1]

    return json.loads(raw.strip())
