"""
Slack 운영 알림 — 워커의 `_alert`/`send_slack_alert` 와 **같은 페이로드**를 쓰는 공용 판.

워커에는 이미 같은 코드가 태스크마다 흩어져 있다(`grant_task._alert`,
`track_google_refund.send_slack_alert`, `voucher_*_task`). API 쪽에서도 알림이 필요해지면서
(PLD-1575 지급 가드) 네 번째 복사본을 만드는 대신 여기에 둔다. 워커 태스크들의 통합은
동작 변경 없는 후속 정리로 남긴다(각 태스크의 함수명이 테스트·로그에 노출돼 있다).

설계 규칙:
  · **url 을 인자로 받는다** — `shared` 는 앱별 config(`API_*`/`WORKER_*` prefix)를 모른다.
  · **절대 예외를 올리지 않는다** — 알림 실패가 지급/거절 판정을 바꿔선 안 된다.
  · 타임아웃은 짧게. 요청 경로(FastAPI 핸들러)에서 호출되므로 webhook 지연이 곧 API 지연이다.
  · 로깅은 **표준 `logging`**. 워커 태스크들은 structlog 를 쓰지만 `shared` 의 의존성 선언
    (`apps/shared/pyproject.toml`)에는 structlog 가 없다 — 여기서 임포트하면 shared 가
    선언되지 않은 패키지에 의존하게 된다(설치 경로에 따라 깨진다).
"""
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# 요청 경로에서 부르는 걸 전제로 한 짧은 타임아웃(워커의 10초보다 짧다).
ALERT_TIMEOUT_SECONDS = 3


def send_slack_alert(url: Optional[str], text: str) -> bool:
    """
    Slack incoming webhook 으로 `text` 전송. 성공 여부를 돌려주지만 **예외는 던지지 않는다**.

    url 이 비어 있으면(미설정) 전송하지 않고 False — 개발/테스트에서 흔한 상태라 warning 한 번만.
    """
    if not url:
        logger.warning("slack alert skipped: webhook url not configured")
        return False
    try:
        resp = requests.post(url, json={"text": text}, timeout=ALERT_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return True
    except Exception as e:  # noqa: BLE001 — 알림 실패로 호출부를 깨지 않는다
        logger.warning("slack alert failed: %s", e)
        return False
