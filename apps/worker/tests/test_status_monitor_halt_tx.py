"""
check_halt_tx 의 발화 조건 테스트.

배경(2026-09-28): 이 알람은 나이 상한이 없는 누적 카운트라, 한 번 박혀서 안 풀리는
영수증이 하나라도 있으면 수동 처리될 때까지 10분마다 영구 재발화했다. 여기서 고정하는
계약은 "오래 박힌 건만 남았으면 조용히 있고, 하루 한 번 따로 보고한다" 이다.

DB 는 안 띄운다 — 바뀐 것은 집계 결과를 받아 쏠지 말지 정하는 분기라, 집계 함수를
경계로 잡고 그 바깥을 검증한다.
"""

from importlib import import_module
from unittest.mock import MagicMock, patch

# `from app.tasks import status_monitor` 로 받으면 **모듈이 아니라 동명의 celery 태스크**가
#   잡힌다(app/tasks/__init__.py 가 태스크를 올리면서 서브모듈 이름을 가린다).
#   그러면 patch.object 가 "태스크에 그런 속성 없다"로 죽는다.
sm = import_module("app.tasks.status_monitor")


def _stats(recent, stale, oldest=None):
    """_stuck_tx_stats 의 반환 형태 (recent, stale, oldest)."""
    return (recent, stale, oldest)


class TestCheckHaltTx:
    def _run(self, recent, stale, oldest=None):
        with patch.object(sm, "_stuck_tx_stats", return_value=_stats(recent, stale, oldest)), patch.object(
            sm, "send_message"
        ) as send:
            sm.check_halt_tx(MagicMock())
        return send

    def test_아무것도_안_막혔으면_안_쏜다(self):
        assert self._run(recent=0, stale=0).call_count == 0

    def test_오래_박힌_것만_남으면_안_쏜다(self):
        """이게 이번 변경의 핵심 — 예전엔 여기서 10분마다 영구 재발화했다."""
        assert self._run(recent=0, stale=3).call_count == 0

    def test_최근_건이_있으면_쏜다(self):
        send = self._run(recent=2, stale=0)
        assert send.call_count == 1
        body = send.call_args[0][2][0]["text"]["text"]
        assert "2" in body

    def test_최근과_장기가_섞이면_합계와_내역을_같이_쏜다(self):
        send = self._run(recent=2, stale=3)
        assert send.call_count == 1
        body = send.call_args[0][2][0]["text"]["text"]
        assert ":: 5" in body  # 합계는 숨기지 않는다
        assert "최근 2건" in body
        assert "3건" in body  # 장기 정체분도 같이 보인다

    def test_최장_경과시간을_분으로_붙인다(self):
        from datetime import datetime, timedelta, timezone

        oldest = datetime.now(tz=timezone.utc) - timedelta(minutes=77)
        body = self._run(recent=1, stale=0, oldest=oldest).call_args[0][2][0]["text"]["text"]
        assert "77분" in body or "76분" in body  # 경계에서 1분 흔들릴 수 있다


class TestReportStaleHaltTx:
    def _run(self, stale, oldest=None):
        with patch.object(sm, "_stuck_tx_stats", return_value=_stats(0, stale, oldest)), patch.object(
            sm, "send_message"
        ) as send:
            sm.report_stale_halt_tx(MagicMock())
        return send

    def test_장기_정체가_없으면_안_쏜다(self):
        assert self._run(stale=0).call_count == 0

    def test_장기_정체가_있으면_하루보고를_쏜다(self):
        from datetime import datetime, timedelta, timezone

        send = self._run(stale=4, oldest=datetime.now(tz=timezone.utc) - timedelta(hours=30))
        assert send.call_count == 1
        title = send.call_args[0][1]
        assert "Stale" in title
        body = send.call_args[0][2][0]["text"]["text"]
        assert "4건" in body
        assert "30시간" in body or "29시간" in body
