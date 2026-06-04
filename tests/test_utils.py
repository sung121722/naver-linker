"""
순수 함수 유닛 테스트 — DB/API 없이 실행
대상: db.get_limit(), main.normalize_date_srv()
"""
import re
from datetime import date

import db
import main


class TestGetLimit:
    def test_free_plan(self):
        assert db.get_limit("free") == 5

    def test_starter_plan(self):
        assert db.get_limit("starter") == 120

    def test_pro_plan(self):
        assert db.get_limit("pro") == 400

    def test_unknown_plan_falls_back_to_free(self):
        assert db.get_limit("unknown") == 5

    def test_empty_string_falls_back_to_free(self):
        assert db.get_limit("") == 5


class TestNormalizeDateSrv:
    """main.normalize_date_srv — 서버사이드 날짜 정규화"""

    def test_valid_date_passthrough(self):
        assert main.normalize_date_srv("2026.04.20") == "2026.04.20"

    def test_empty_string_returns_empty(self):
        assert main.normalize_date_srv("") == ""

    def test_relative_time_returns_today(self):
        today = date.today().strftime("%Y.%m.%d")
        assert main.normalize_date_srv("4분 전") == today
        assert main.normalize_date_srv("어제") == today
        assert main.normalize_date_srv("10시간 전") == today

    def test_result_format_is_yyyy_mm_dd(self):
        result = main.normalize_date_srv("방금 전")
        assert re.match(r"^\d{4}\.\d{2}\.\d{2}$", result), f"포맷 오류: {result}"

    def test_partial_date_is_normalized(self):
        # "2026.4.5" 처럼 패딩 없는 날짜 → 오늘로 변환
        today = date.today().strftime("%Y.%m.%d")
        assert main.normalize_date_srv("2026.4.5") == today


class TestPlanPrices:
    def test_starter_price(self):
        assert main.PLAN_PRICES["starter"] == 9900

    def test_pro_price(self):
        assert main.PLAN_PRICES["pro"] == 19900
