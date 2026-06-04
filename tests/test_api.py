"""
FastAPI 엔드포인트 테스트
- 실제 DB/외부 API 없이 mock으로 대체
- 핵심 시나리오: 수집, 검색 rate limit, 결제 플로우
"""
import pytest


# ── /api/session ─────────────────────────────────────────
class TestSession:
    def test_returns_session_id(self, client):
        resp = client.get("/api/session")
        assert resp.status_code == 200
        assert "session_id" in resp.json()

    def test_session_id_is_uuid_format(self, client):
        import re
        sid = client.get("/api/session").json()["session_id"]
        assert re.match(r"[0-9a-f-]{36}", sid)


# ── /api/index ───────────────────────────────────────────
class TestIndex:
    SAMPLE_POSTS = [
        {"title": "노인 복지 혜택", "url": "https://blog.naver.com/t/1", "date": "2026.04.20"},
        {"title": "기초연금 신청법", "url": "https://blog.naver.com/t/2", "date": "2026.03.15"},
    ]

    def test_extension_mode_returns_ok(self, client, mock_db):
        _, cur = mock_db
        cur.fetchone.return_value = {"plan": "free", "search_count": 0, "is_paid": 0}

        resp = client.post("/api/index", json={
            "blog_id": "testblog",
            "source": "extension",
            "posts": self.SAMPLE_POSTS,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["post_count"] == 2

    def test_returns_session_id(self, client, mock_db):
        _, cur = mock_db
        cur.fetchone.return_value = {"plan": "free", "search_count": 0, "is_paid": 0}

        resp = client.post("/api/index", json={
            "blog_id": "testblog",
            "source": "extension",
            "posts": self.SAMPLE_POSTS,
        })
        assert "session_id" in resp.json()
        assert len(resp.json()["session_id"]) > 0


# ── IP 등록 제한 ─────────────────────────────────────────
class TestIpRegistrationLimit:
    POSTS = [{"title": "글", "url": "https://blog.naver.com/t/1", "date": "2026.01.01"}]

    def _post_index(self, client, blog_id):
        return client.post("/api/index", json={
            "blog_id": blog_id,
            "source": "extension",
            "posts": self.POSTS,
        })

    def test_first_registration_allowed(self, client, monkeypatch, mock_db):
        _, cur = mock_db
        cur.fetchone.return_value = {"plan": "free", "search_count": 0, "is_paid": 0}
        monkeypatch.setattr("db.check_and_record_ip_registration", lambda ip, bid: True)

        resp = self._post_index(client, "myblog")
        assert resp.status_code == 200

    def test_same_blog_reindex_allowed(self, client, monkeypatch, mock_db):
        _, cur = mock_db
        cur.fetchone.return_value = {"plan": "free", "search_count": 0, "is_paid": 0}
        monkeypatch.setattr("db.check_and_record_ip_registration", lambda ip, bid: True)

        self._post_index(client, "myblog")
        resp = self._post_index(client, "myblog")  # 동일 blogId 재수집
        assert resp.status_code == 200

    def test_fourth_different_blog_blocked(self, client, monkeypatch):
        monkeypatch.setattr("db.check_and_record_ip_registration", lambda ip, bid: False)

        resp = self._post_index(client, "blog4")
        assert resp.status_code == 429
        assert "3개" in resp.json()["detail"]

    def test_db_registration_logic_allows_up_to_limit(self, monkeypatch):
        """DB 함수 자체 로직 검증: 3개까지 허용, 4번째 차단"""
        import db
        registered = set()

        def fake_get_conn():
            from unittest.mock import MagicMock
            conn = MagicMock()
            cur = MagicMock()
            conn.cursor.return_value = cur
            cur.fetchall.return_value = [{"blog_id": b} for b in registered]
            def fake_execute(sql, params=None):
                if params and "INSERT INTO ip_registrations" in sql:
                    registered.add(params[1])
            cur.execute.side_effect = fake_execute
            return conn

        monkeypatch.setattr("db.get_conn", fake_get_conn)

        assert db.check_and_record_ip_registration("1.2.3.4", "blog1") is True
        assert db.check_and_record_ip_registration("1.2.3.4", "blog2") is True
        assert db.check_and_record_ip_registration("1.2.3.4", "blog3") is True
        assert db.check_and_record_ip_registration("1.2.3.4", "blog4") is False  # 초과

    def test_same_blog_reindex_doesnt_count(self, monkeypatch):
        """동일 blogId 재수집은 카운트 증가 없이 허용"""
        import db
        registered = {"myblog"}

        def fake_get_conn():
            from unittest.mock import MagicMock
            conn = MagicMock()
            cur = MagicMock()
            conn.cursor.return_value = cur
            cur.fetchall.return_value = [{"blog_id": b} for b in registered]
            return conn

        monkeypatch.setattr("db.get_conn", fake_get_conn)

        # 이미 등록된 blog 재수집 → 항상 허용
        assert db.check_and_record_ip_registration("1.2.3.4", "myblog") is True


# ── /api/search ──────────────────────────────────────────
class TestSearch:
    BASE_PAYLOAD = {
        "session_id": "test-session-id",
        "blog_id": "testblog",
        "keyword": "노인 복지",
        "top_n": 5,
    }

    def test_returns_402_when_free_limit_exceeded(self, client, monkeypatch):
        monkeypatch.setattr("db.get_search_count",   lambda sid: (0, "free"))
        monkeypatch.setattr("db.get_ip_search_count", lambda ip: 5)  # 한도 초과

        resp = client.post("/api/search", json=self.BASE_PAYLOAD)
        assert resp.status_code == 402

    def test_returns_200_with_results(self, client, monkeypatch, mock_matcher):
        monkeypatch.setattr("db.get_search_count",   lambda sid: (0, "free"))
        monkeypatch.setattr("db.get_ip_search_count", lambda ip: 0)
        monkeypatch.setattr("db.get_posts", lambda bid: [
            {"title": "노인 복지 혜택", "url": "https://blog.naver.com/t/1", "date": "2026.04.20"},
        ])
        monkeypatch.setattr("db.increment_search",    lambda sid, bid: None)
        monkeypatch.setattr("db.increment_ip_search", lambda ip: None)

        resp = client.post("/api/search", json=self.BASE_PAYLOAD)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert isinstance(data["results"], list)

    def test_returns_404_when_no_posts(self, client, monkeypatch):
        monkeypatch.setattr("db.get_search_count",   lambda sid: (0, "free"))
        monkeypatch.setattr("db.get_ip_search_count", lambda ip: 0)
        monkeypatch.setattr("db.get_posts",           lambda bid: [])  # 글 없음

        resp = client.post("/api/search", json=self.BASE_PAYLOAD)
        assert resp.status_code == 404

    def test_paid_plan_uses_session_count(self, client, monkeypatch, mock_matcher):
        """유료 플랜은 IP가 아닌 세션 카운트로 제한"""
        monkeypatch.setattr("db.get_search_count",   lambda sid: (119, "starter"))  # 한도 직전
        monkeypatch.setattr("db.get_posts", lambda bid: [
            {"title": "글", "url": "https://blog.naver.com/t/1", "date": "2026.01.01"},
        ])
        monkeypatch.setattr("db.increment_search", lambda sid, bid: None)

        resp = client.post("/api/search", json=self.BASE_PAYLOAD)
        assert resp.status_code == 200

    def test_paid_plan_blocked_when_limit_exceeded(self, client, monkeypatch):
        monkeypatch.setattr("db.get_search_count", lambda sid: (120, "starter"))  # 한도 초과

        resp = client.post("/api/search", json=self.BASE_PAYLOAD)
        assert resp.status_code == 402

    def test_result_dates_are_normalized(self, client, monkeypatch):
        """DB에 '4분 전' 같은 값이 있어도 YYYY.MM.DD로 변환"""
        from datetime import date
        monkeypatch.setattr("db.get_search_count",   lambda sid: (0, "free"))
        monkeypatch.setattr("db.get_ip_search_count", lambda ip: 0)
        monkeypatch.setattr("db.get_posts", lambda bid: [
            {"title": "최신글", "url": "https://blog.naver.com/t/1", "date": "4분 전"},
        ])
        monkeypatch.setattr("matcher.find_related", lambda posts, kw, n: [
            {"title": "최신글", "url": "https://blog.naver.com/t/1",
             "reason": "관련", "date": "4분 전"},
        ])
        monkeypatch.setattr("db.increment_search",    lambda sid, bid: None)
        monkeypatch.setattr("db.increment_ip_search", lambda ip: None)

        resp = client.post("/api/search", json=self.BASE_PAYLOAD)
        assert resp.status_code == 200
        for r in resp.json()["results"]:
            assert r["date"] != "4분 전", "상대시간이 그대로 반환됨"
            assert r["date"] == date.today().strftime("%Y.%m.%d")


# ── /api/payment/order ───────────────────────────────────
class TestPaymentOrder:
    def test_invalid_plan_returns_400(self, client, mock_db):
        resp = client.post("/api/payment/order", json={
            "session_id": "test-session",
            "plan": "enterprise",  # 존재하지 않는 플랜
        })
        assert resp.status_code == 400

    def test_missing_session_returns_400(self, client, mock_db):
        resp = client.post("/api/payment/order", json={
            "session_id": "",
            "plan": "starter",
        })
        assert resp.status_code == 400

    def test_starter_order_returns_correct_amount(self, client, mock_db):
        resp = client.post("/api/payment/order", json={
            "session_id": "test-session-abc",
            "plan": "starter",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["amount"] == 9900
        assert "order_id" in data
        assert "client_key" in data

    def test_pro_order_returns_correct_amount(self, client, mock_db):
        resp = client.post("/api/payment/order", json={
            "session_id": "test-session-abc",
            "plan": "pro",
        })
        assert resp.status_code == 200
        assert resp.json()["amount"] == 19900

    def test_order_id_contains_plan_name(self, client, mock_db):
        resp = client.post("/api/payment/order", json={
            "session_id": "test-session-abc",
            "plan": "starter",
        })
        order_id = resp.json()["order_id"]
        assert "starter" in order_id
        assert order_id.startswith("NL-")


# ── /api/plan/:session_id ────────────────────────────────
class TestGetPlan:
    def test_returns_plan_info(self, client, monkeypatch):
        monkeypatch.setattr("db.get_plan_info", lambda sid: {
            "plan": "starter", "search_count": 10, "daily_limit": 120
        })
        resp = client.get("/api/plan/test-session")
        assert resp.status_code == 200
        data = resp.json()
        assert data["plan"] == "starter"
        assert data["daily_limit"] == 120

    def test_unknown_session_returns_free(self, client, monkeypatch):
        monkeypatch.setattr("db.get_plan_info", lambda sid: {
            "plan": "free", "search_count": 0, "daily_limit": 5
        })
        resp = client.get("/api/plan/nonexistent-session")
        assert resp.status_code == 200
        assert resp.json()["plan"] == "free"
