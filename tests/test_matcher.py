"""
matcher.py 테스트 — Anthropic API 호출을 mock으로 대체
실제 API 키 없이 로직 검증
"""
import pytest
from unittest.mock import MagicMock, patch


SAMPLE_POSTS = [
    {"title": "노인 복지 혜택 총정리",    "url": "https://blog.naver.com/t/1", "date": "2026.04.20"},
    {"title": "기초연금 신청 완벽 가이드", "url": "https://blog.naver.com/t/2", "date": "2026.03.15"},
    {"title": "Medicare 혜택 안내",       "url": "https://blog.naver.com/t/3", "date": "2026.02.10"},
]


def _make_tool_response(tool_name: str, tool_input: dict):
    """Anthropic tool_use 응답 구조를 흉내내는 mock 생성"""
    block = MagicMock()
    block.type = "tool_use"
    block.name = tool_name
    block.input = tool_input

    response = MagicMock()
    response.content = [block]
    return response


class TestFindRelated:
    def test_returns_list_of_recommendations(self):
        mock_resp = _make_tool_response("recommend_posts", {
            "recommendations": [
                {"title": "노인 복지 혜택 총정리",
                 "url": "https://blog.naver.com/t/1",
                 "reason": "복지 키워드 직접 매칭"},
            ]
        })
        with patch("matcher._get_client") as mock_client:
            mock_client.return_value.messages.create.return_value = mock_resp
            import matcher
            results = matcher.find_related(SAMPLE_POSTS, "복지 혜택", top_n=1)

        assert isinstance(results, list)
        assert len(results) == 1
        assert results[0]["title"] == "노인 복지 혜택 총정리"

    def test_date_is_attached_from_posts(self):
        """URL 기반으로 posts의 date를 results에 붙이는지 검증"""
        mock_resp = _make_tool_response("recommend_posts", {
            "recommendations": [
                {"title": "노인 복지 혜택 총정리",
                 "url": "https://blog.naver.com/t/1",
                 "reason": "관련"},
            ]
        })
        with patch("matcher._get_client") as mock_client:
            mock_client.return_value.messages.create.return_value = mock_resp
            import matcher
            results = matcher.find_related(SAMPLE_POSTS, "복지", top_n=1)

        assert results[0]["date"] == "2026.04.20"

    def test_returns_empty_on_no_tool_use(self):
        """Claude가 tool 없이 응답하면 빈 리스트 반환"""
        response = MagicMock()
        response.content = []  # tool_use 없음

        with patch("matcher._get_client") as mock_client:
            mock_client.return_value.messages.create.return_value = response
            import matcher
            results = matcher.find_related(SAMPLE_POSTS, "복지", top_n=5)

        assert results == []

    def test_top_n_is_passed_to_prompt(self):
        """top_n 값이 실제 API 호출에 전달되는지 검증"""
        mock_resp = _make_tool_response("recommend_posts", {"recommendations": []})

        with patch("matcher._get_client") as mock_client:
            mock_client.return_value.messages.create.return_value = mock_resp
            import matcher
            matcher.find_related(SAMPLE_POSTS, "복지", top_n=10)

        call_kwargs = mock_client.return_value.messages.create.call_args
        messages = call_kwargs.kwargs.get("messages") or call_kwargs.args[0]
        # top_n=10이 프롬프트에 포함되었는지 확인
        prompt_text = str(messages)
        assert "10" in prompt_text


class TestFindDuplicates:
    def test_returns_no_duplicate_when_unrelated(self):
        mock_resp = _make_tool_response("check_duplicates", {
            "has_duplicate": False,
            "similar_posts": [],
        })
        with patch("matcher._get_client") as mock_client:
            mock_client.return_value.messages.create.return_value = mock_resp
            import matcher
            result = matcher.find_duplicates(SAMPLE_POSTS, "전혀 다른 주제", top_n=5)

        assert result["has_duplicate"] is False
        assert result["similar_posts"] == []

    def test_returns_duplicate_with_similarity_score(self):
        mock_resp = _make_tool_response("check_duplicates", {
            "has_duplicate": True,
            "similar_posts": [
                {"title": "노인 복지 혜택 총정리",
                 "url": "https://blog.naver.com/t/1",
                 "date": "2026.04.20",
                 "similarity": 85,
                 "overlap": "복지 혜택 키워드 중복"},
            ],
        })
        with patch("matcher._get_client") as mock_client:
            mock_client.return_value.messages.create.return_value = mock_resp
            import matcher
            result = matcher.find_duplicates(SAMPLE_POSTS, "노인 복지 혜택", top_n=5)

        assert result["has_duplicate"] is True
        assert result["similar_posts"][0]["similarity"] == 85

    def test_fallback_on_empty_response(self):
        """tool 응답 없으면 기본값 반환"""
        response = MagicMock()
        response.content = []

        with patch("matcher._get_client") as mock_client:
            mock_client.return_value.messages.create.return_value = response
            import matcher
            result = matcher.find_duplicates(SAMPLE_POSTS, "복지", top_n=5)

        assert result == {"has_duplicate": False, "similar_posts": []}
