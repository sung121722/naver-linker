"""
테스트 하네스 공통 설정
- psycopg2 미설치 환경에서도 실행 가능 (sys.modules mock)
- FastAPI TestClient 제공
- Anthropic API 호출 없이 matcher 테스트 가능
"""
import sys
from unittest.mock import MagicMock, patch
import pytest


# ── psycopg2를 sys.modules에서 통째로 mock (로컬 미설치 대응) ──
_psycopg2 = MagicMock()
_psycopg2.extras.RealDictCursor = dict  # db.py가 cursor_factory로 사용
sys.modules.setdefault("psycopg2",        _psycopg2)
sys.modules.setdefault("psycopg2.extras", _psycopg2.extras)


# ── DB mock factory ──────────────────────────────────────
def make_mock_conn(one_row=None, all_rows=None):
    """DB 커넥션 + 커서를 흉내내는 mock 객체 생성"""
    conn = MagicMock()
    cur  = MagicMock()
    conn.cursor.return_value = cur
    cur.fetchone.return_value = one_row
    cur.fetchall.return_value = all_rows or []
    return conn, cur


# ── FastAPI TestClient (DB init mock 포함) ────────────────
# db.init_db()가 import 시점에 실행되므로 미리 patch
with patch("db.init_db"):
    from fastapi.testclient import TestClient
    import main  # noqa: E402

_app_client = TestClient(main.app)


@pytest.fixture
def client():
    """FastAPI TestClient fixture"""
    return _app_client


@pytest.fixture
def mock_db(monkeypatch):
    """
    테스트별 DB 커넥션 fixture.
    반환값: (conn, cur) — cur.fetchone / cur.fetchall 직접 설정 가능.

    사용 예:
        def test_something(mock_db):
            conn, cur = mock_db
            cur.fetchone.return_value = {"plan": "free", "search_count": 0}
    """
    conn, cur = make_mock_conn()
    monkeypatch.setattr("db.get_conn", lambda: conn)
    return conn, cur


@pytest.fixture
def mock_matcher(monkeypatch):
    """
    Anthropic API 호출 없이 matcher를 테스트할 때 사용.
    반환값: (find_related_mock, find_duplicates_mock)
    """
    related_mock = MagicMock(return_value=[
        {"title": "노인 복지 혜택 총정리", "url": "https://blog.naver.com/test/1",
         "reason": "복지 키워드 일치", "date": "2026.04.20"},
    ])
    dup_mock = MagicMock(return_value={
        "has_duplicate": False,
        "similar_posts": [],
    })
    monkeypatch.setattr("matcher.find_related",   related_mock)
    monkeypatch.setattr("matcher.find_duplicates", dup_mock)
    return related_mock, dup_mock
