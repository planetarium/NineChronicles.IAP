"""
check_halt_tx 계약 테스트.

배경(2026-09-28): 이 알람은 나이 상한이 없는 누적 카운트라, 한 번 박혀서 안 풀리는
영수증이 하나라도 있으면 수동 처리될 때까지 10분마다 영구 재발화했다. 여기서 고정하는
계약은 "오래 박힌 건만 남았으면 조용히 있고, 하루 한 번 따로 보고한다" 이다.

집계 쿼리는 **실제로 실행해서** 검증한다(SQLite 인메모리). 집계 함수를 mock 으로만
막으면 두 FILTER 컬럼 순서가 뒤바뀌어도 전부 통과하는데, 그 버그의 결과가 하필
'영구 침묵' 이라 이 변경이 가장 두려워하는 실패 모드다.
"""

from datetime import datetime, timedelta, timezone
from importlib import import_module
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from shared.enums import ReceiptStatus, Store, TxStatus
from shared.models.receipt import Receipt

# `from app.tasks import status_monitor` 로 받으면 **모듈이 아니라 동명의 celery 태스크**가
#   잡힌다(app/tasks/__init__.py 가 태스크를 올리면서 서브모듈 이름을 가린다).
#   그러면 patch.object 가 "태스크에 그런 속성 없다"로 죽는다.
sm = import_module("app.tasks.status_monitor")


@compiles(JSONB, "sqlite")
def _jsonb_as_json(type_, compiler, **kw):  # noqa: ANN001
    """receipt.data 가 JSONB 라 SQLite 로는 그대로 렌더가 안 된다."""
    return "JSON"


@pytest.fixture()
def sess():
    engine = create_engine("sqlite://")
    Receipt.__table__.create(engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


NOW = datetime(2026, 9, 29, 4, 0, tzinfo=timezone.utc)


def _add(sess, minutes_ago, tx_status=TxStatus.STAGED, status=ReceiptStatus.VALID):
    sess.add(
        Receipt(
            store=Store.GOOGLE,
            order_id="o",
            package_name="com.planetariumlabs.ninechroniclesmobile",
            data={},
            status=status,
            tx_status=tx_status,
            created_at=NOW - timedelta(minutes=minutes_ago),
        )
    )


class TestStuckTxStats:
    """집계 쿼리 자체 — 컬럼 순서와 버킷 경계를 실제 실행으로 고정한다."""

    def test_버킷이_나이로_갈리고_순서가_맞다(self, sess):
        _add(sess, 2)  # 5분 미만 → 대상 아님
        _add(sess, 30)  # recent
        _add(sess, 45)  # recent (이게 recent 최고령)
        _add(sess, 60 * 10)  # stale
        _add(sess, 60 * 30)  # stale (이게 전체 최고령)
        _add(sess, 30, tx_status=TxStatus.SUCCESS)  # 상태 불일치 → 대상 아님
        _add(sess, 30, status=ReceiptStatus.INVALID)  # 상태 불일치 → 대상 아님
        sess.commit()

        recent, stale, oldest, recent_oldest = sm._stuck_tx_stats(sess, NOW)

        assert recent == 2
        assert stale == 2
        # 전체 최고령은 stale 쪽(30시간), recent 최고령은 45분짜리여야 한다.
        #   두 min 컬럼이 뒤바뀌면 여기서 잡힌다.
        #   SQLite 는 tz 를 떼고 돌려주므로 naive 끼리 비교한다(값은 UTC 그대로다).
        naive_now = NOW.replace(tzinfo=None)
        assert oldest == naive_now - timedelta(minutes=60 * 30)
        assert recent_oldest == naive_now - timedelta(minutes=45)

    def test_대상이_없으면_0과_None(self, sess):
        _add(sess, 2)  # 5분 미만뿐
        sess.commit()
        assert sm._stuck_tx_stats(sess, NOW) == (0, 0, None, None)

    def test_오래된_것만_있으면_recent가_0이다(self, sess):
        _add(sess, 60 * 9)
        sess.commit()
        recent, stale, oldest, recent_oldest = sm._stuck_tx_stats(sess, NOW)
        assert (recent, stale) == (0, 1)
        assert recent_oldest is None  # 침묵 분기가 타는 조건


class TestCheckHaltTx:
    def _run(self, recent, stale, oldest=None, recent_oldest=None):
        stats = (recent, stale, oldest, recent_oldest)
        with patch.object(sm, "_stuck_tx_stats", return_value=stats), patch.object(
            sm, "send_message"
        ) as send:
            sm.check_halt_tx(MagicMock())
        return send

    def test_아무것도_안_막혔으면_안_쏜다(self):
        assert self._run(recent=0, stale=0).call_count == 0

    def test_오래_박힌_것만_남으면_안_쏜다(self):
        """이게 이번 변경의 핵심 — 예전엔 여기서 10분마다 영구 재발화했다."""
        assert self._run(recent=0, stale=3, oldest=NOW).call_count == 0

    def test_최근_건이_있으면_쏜다(self):
        send = self._run(recent=2, stale=0)
        assert send.call_count == 1
        assert ":: 2" in send.call_args[0][2][0]["text"]["text"]

    def test_최근과_장기가_섞이면_합계와_내역을_같이_쏜다(self):
        now = datetime.now(tz=timezone.utc)
        send = self._run(
            recent=2,
            stale=3,
            oldest=now - timedelta(hours=30),
            recent_oldest=now - timedelta(minutes=12),
        )
        body = send.call_args[0][2][0]["text"]["text"]
        assert ":: 5" in body  # 합계는 숨기지 않는다
        assert "최근 2건" in body
        assert "3건" in body  # 장기 정체분도 같이 보인다
        # 섞였을 때 "최장" 은 recent 버킷 기준이어야 진단에 쓸 수 있다(12분이지 30시간이 아니다).
        assert "최장 12분" in body or "최장 11분" in body

    def test_경계시간_문구가_상수에서_나온다(self):
        """상수를 바꿨는데 메시지가 '6시간' 으로 남아 거짓말하는 걸 막는다."""
        now = datetime.now(tz=timezone.utc)
        with patch.object(sm, "STUCK_STALE_AFTER", timedelta(hours=9)):
            send = self._run(recent=1, stale=1, oldest=now - timedelta(hours=20))
        assert "9시간 이상" in send.call_args[0][2][0]["text"]["text"]


class TestReportStaleHaltTx:
    def _run(self, stale, oldest=None):
        with patch.object(
            sm, "_stuck_tx_stats", return_value=(0, stale, oldest, None)
        ), patch.object(sm, "send_message") as send:
            sm.report_stale_halt_tx(MagicMock())
        return send

    def test_장기_정체가_없으면_안_쏜다(self):
        assert self._run(stale=0).call_count == 0

    def test_장기_정체가_있으면_멘션과_함께_하루보고를_쏜다(self):
        send = self._run(
            stale=4, oldest=datetime.now(tz=timezone.utc) - timedelta(hours=30)
        )
        assert send.call_count == 1
        assert "Stale" in send.call_args[0][1]
        body = send.call_args[0][2][0]["text"]["text"]
        assert "4건" in body
        assert "30시간" in body or "29시간" in body
        # 반복 알람에서 넘겨받은 "수동 확인" 책임이 여기 있다 — 조용하면 아무도 안 본다.
        assert "<@UCKUGBH37>" in body


class TestIsDailySlot:
    @pytest.mark.parametrize("minute", [0, 5, 9])
    def test_정각_근처_10분_창은_슬롯이다(self, minute):
        assert sm.is_daily_slot(datetime(2026, 9, 29, 3, minute, tzinfo=timezone.utc))

    def test_정각에서_10분_지나면_아니다(self):
        assert not sm.is_daily_slot(datetime(2026, 9, 29, 3, 10, tzinfo=timezone.utc))

    def test_다른_시각은_아니다(self):
        assert not sm.is_daily_slot(datetime(2026, 9, 29, 4, 0, tzinfo=timezone.utc))

    def test_창이_10분이라_10분_주기_태스크에선_하루_한_번만_참이다(self):
        hits = [
            m
            for m in range(0, 60, 10)
            if sm.is_daily_slot(datetime(2026, 9, 29, 3, m, tzinfo=timezone.utc))
        ]
        assert hits == [0]
