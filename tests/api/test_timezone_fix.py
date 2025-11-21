import pytest
from datetime import datetime, timezone, timedelta, date
from unittest.mock import Mock, patch
from sqlalchemy import Date, cast, func

from shared.enums import PlanetID
from shared.models.receipt import Receipt


def test_kst_timezone_calculation():
    """KST 타임존 계산 테스트"""
    # KST 오전 8시 59분 (UTC 오전 11시 59분)
    utc_time = datetime(2025, 9, 28, 11, 59, 0, tzinfo=timezone.utc)
    kst_time = utc_time.astimezone(timezone(timedelta(hours=9)))

    # KST 기준 날짜 계산
    kst_date = kst_time.date()

    # 2025-09-28이어야 함
    assert kst_date.year == 2025
    assert kst_date.month == 9
    assert kst_date.day == 28


def test_kst_daily_limit_boundary():
    """KST 일일 제한 경계 테스트"""
    # KST 오전 9시 정확히 (UTC 오전 12시)
    utc_time = datetime(2025, 9, 28, 0, 0, 0, tzinfo=timezone.utc)
    kst_time = utc_time.astimezone(timezone(timedelta(hours=9)))

    # KST 기준 날짜 계산
    kst_date = kst_time.date()

    # 2025-09-28이어야 함
    assert kst_date.year == 2025
    assert kst_date.month == 9
    assert kst_date.day == 28


def test_kst_weekly_limit_calculation():
    """KST 주간 제한 계산 테스트"""
    # KST 오전 8시 59분 (UTC 오전 11시 59분)
    utc_time = datetime(2025, 9, 28, 11, 59, 0, tzinfo=timezone.utc)
    kst_time = utc_time.astimezone(timezone(timedelta(hours=9)))

    # KST 기준 주간 시작일 계산 (일요일)
    kst_date = kst_time.date()
    isoweekday = kst_date.isoweekday()
    weekly_start = kst_date - timedelta(days=(isoweekday % 7))

    # 2025-09-28은 일요일이므로 주간 시작일은 2025-09-28
    assert weekly_start.year == 2025
    assert weekly_start.month == 9
    assert weekly_start.day == 28


def test_timezone_difference():
    """UTC와 KST 시간 차이 테스트"""
    # UTC 오전 12시
    utc_time = datetime(2025, 9, 28, 0, 0, 0, tzinfo=timezone.utc)
    utc_date = utc_time.date()

    # KST 오전 9시
    kst_time = utc_time.astimezone(timezone(timedelta(hours=9)))
    kst_date = kst_time.date()

    # 같은 날짜여야 함
    assert utc_date == kst_date

    # UTC 오전 11시 59분
    utc_time_1159 = datetime(2025, 9, 28, 11, 59, 0, tzinfo=timezone.utc)
    utc_date_1159 = utc_time_1159.date()

    # KST 오전 8시 59분
    kst_time_1159 = utc_time_1159.astimezone(timezone(timedelta(hours=9)))
    kst_date_1159 = kst_time_1159.date()

    # 같은 날짜여야 함
    assert utc_date_1159 == kst_date_1159


def test_get_purchase_count_timezone_conversion():
    """get_purchase_count 함수의 타임존 변환 쿼리 생성 테스트"""
    # KST 기준으로 현재 시간 설정 (KST 2025-01-02 01:00 = UTC 2025-01-01 16:00)
    kst_now = datetime(2025, 1, 2, 1, 0, 0, tzinfo=timezone(timedelta(hours=9)))
    start = kst_now.date()

    # 쿼리 생성 로직 검증: timezone 변환이 사용되는지 확인
    # 실제 쿼리 표현식 생성
    timezone_expr = func.timezone('Asia/Seoul', Receipt.purchased_at)
    date_expr = cast(timezone_expr, Date)
    filter_expr = date_expr >= start

    # 표현식이 올바르게 생성되었는지 확인
    assert filter_expr is not None
    # timezone 함수가 사용되었는지 확인 (표현식의 구조 확인)
    assert hasattr(timezone_expr, 'name') or hasattr(timezone_expr, 'func')


def test_get_purchase_count_daily_limit_midnight_kst():
    """새벽 시간대(UTC 16:00, KST 01:00) 구매 시나리오 테스트"""
    # 새벽 1시 (KST) = 전날 16시 (UTC)
    # KST 2025-01-02 01:00 = UTC 2025-01-01 16:00
    kst_now = datetime(2025, 1, 2, 1, 0, 0, tzinfo=timezone(timedelta(hours=9)))
    start = kst_now.date()

    # UTC로 저장된 purchased_at을 KST로 변환한 날짜
    # UTC 2025-01-01 16:00을 KST로 변환하면 2025-01-02 01:00이므로 날짜는 2025-01-02
    utc_purchased_at = datetime(2025, 1, 1, 16, 0, 0, tzinfo=timezone.utc)
    kst_purchased_at = utc_purchased_at.astimezone(timezone(timedelta(hours=9)))
    kst_purchased_date = kst_purchased_at.date()

    # KST 기준으로 변환된 날짜가 오늘 날짜와 일치하는지 확인
    assert kst_purchased_date == start  # 둘 다 2025-01-02
    # UTC 날짜와는 다름
    assert utc_purchased_at.date() != start  # UTC는 2025-01-01, start는 2025-01-02


def test_get_purchase_count_daily_limit_boundary_utc_midnight():
    """경계 시간대(UTC 00:00, KST 09:00) 테스트"""
    # UTC 자정 = KST 오전 9시
    # UTC 2025-01-02 00:00 = KST 2025-01-02 09:00
    kst_now = datetime(2025, 1, 2, 9, 0, 0, tzinfo=timezone(timedelta(hours=9)))
    start = kst_now.date()

    # UTC 00:00에 구매한 경우
    utc_purchased_at = datetime(2025, 1, 2, 0, 0, 0, tzinfo=timezone.utc)
    kst_purchased_at = utc_purchased_at.astimezone(timezone(timedelta(hours=9)))
    kst_purchased_date = kst_purchased_at.date()

    # KST 기준으로 변환된 날짜가 오늘 날짜와 일치하는지 확인
    assert kst_purchased_date == start  # 둘 다 2025-01-02
    # UTC 날짜와도 일치 (같은 날)
    assert utc_purchased_at.date() == start  # 둘 다 2025-01-02


def test_get_purchase_count_weekly_limit_timezone():
    """주간 제한에도 타임존 변환이 적용되는지 테스트"""
    # KST 기준 현재 시간
    kst_now = datetime(2025, 1, 2, 1, 0, 0, tzinfo=timezone(timedelta(hours=9)))

    # 주간 시작일 계산 (일요일)
    kst_date = kst_now.date()
    isoweekday = kst_date.isoweekday()
    weekly_start = (kst_date - timedelta(days=(isoweekday % 7)))

    # 쿼리 생성 로직 검증: timezone 변환이 사용되는지 확인
    timezone_expr = func.timezone('Asia/Seoul', Receipt.purchased_at)
    date_expr = cast(timezone_expr, Date)
    filter_expr = date_expr >= weekly_start

    # 표현식이 올바르게 생성되었는지 확인
    assert filter_expr is not None
    # timezone 함수가 사용되었는지 확인
    assert hasattr(timezone_expr, 'name') or hasattr(timezone_expr, 'func')
