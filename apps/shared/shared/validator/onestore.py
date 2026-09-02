"""원스토어(ONE Store) 구매 검증.

문서: https://onestore-dev.gitbook.io/dev/tools/billing/v21/serverapi

Google 처럼 SDK 가 있는 게 아니라 그냥 REST 라서 `web.py`(Stripe) 보다는
`apple.py`(HTTP + Bearer) 에 가깝다. 다른 점은 **토큰을 우리가 직접 받아 와야** 한다는 것.

## 환경

`ONESTORE` 하나뿐이고 `*_TEST` 변종이 없다. 영수증 봉투가 상용/검증 환경 동일이라 서버가
구분할 수 없기 때문이다(`enums.py` 의 `Store.ONESTORE` 주석). 대신 **호스트**가 갈린다:

    검증(개발)  https://sbpp.onestore.net
    상용        https://iap-apis.onestore.net

client_id/client_secret 은 앱 단위 한 벌이라 양쪽이 같다. 구매 기록이 환경별로 분리돼 있어
샌드박스 구매를 상용 호스트에 물으면 `NoSuchData` 로 떨어진다 — 즉 호스트만 배포별로 맞추면
샌드박스 영수증이 메인넷에서 지급으로 새지 않는다(fail-closed).

## 이 모듈이 지키는 것 / 못 지키는 것

영수증의 `Payload.signature` 는 **검증하지 않는다.** 대신 (productId, purchaseToken) 으로
원스토어에 직접 물어서 판단한다. 그래서:

- 싼 상품 토큰에 비싼 `productId` 를 붙이는 치환은 **"토큰과 안 맞는 productId 로 조회하면
  404" 라는 원스토어 동작 하나에만** 막혀 있다. 오픈 전에 샌드박스에서 실측할 것.
- 구매와 요청자(agentAddress) 사이에 암호학적 결합이 없다 — 토큰을 손에 넣은 쪽이 먼저 보내면
  가져간다. Google 의 `obfuscatedExternalAccountId` 에 대응하는 자리가 `developerPayload` 라,
  닫으려면 클라이언트가 구매 시 거기에 agent/avatar 를 심고 여기서 대조해야 한다.
  (현재 Google 경로도 같은 수준이라 이번 범위에서는 맞추지 않았다.)
"""

import threading
import time
import urllib.parse
from typing import Optional, Tuple

import requests

from shared.enums import OneStoreConsumptionState, OneStorePurchaseState
from shared.schemas.receipt import OneStorePurchaseSchema

# 이 호출은 `/purchase/request` 안에서, 그것도 pg_advisory_xact_lock 을 잡은 뒤에 일어난다
#   (purchase.py 의 dedup 주석 참조). 스레드와 DB 커넥션을 물고 기다리는 시간이라
#   짧게 잡는다. 최악 경로는 토큰 발급 + 조회 + (401 이면) 재발급 + 재조회 = 4×timeout.
HTTP_TIMEOUT = 5
# 문서: "기본적으로 3600초의 유효기간이 있으며, 유효기간이 만료되거나 600초 미만으로 남은 경우"
#   신규 발급 가능. 그래서 잔여 600초를 캐시 만료선으로 쓴다.
TOKEN_REFRESH_MARGIN = 600

# (host, client_id) -> (access_token, monotonic 만료시각)
#   프로세스 로컬이다. API 는 워커 프로세스가 여러 개라 프로세스 수만큼 토큰을 들지만,
#   원스토어는 유효기간 안에 다시 요청하면 쓰던 토큰을 돌려주므로 문제되지 않는다.
#   single-flight 는 안 건다 — 만료 경계에서 동시 요청 수만큼 발급 POST 가 나가지만 무해하다.
_token_cache: dict[Tuple[str, str], Tuple[str, float]] = {}
_token_lock = threading.Lock()


def clear_token_cache() -> None:
    """테스트용. 운영 코드에서 부를 일은 없다."""
    with _token_lock:
        _token_cache.clear()


def is_onestore_configured(host: Optional[str], client_id: Optional[str], client_secret: Optional[str]) -> bool:
    """시크릿이 배선됐는지. 호출자가 **영수증을 만들기 전에** 확인하는 용도.

    검증 단계까지 와서 실패하면 그 영수증이 INVALID 로 굳고, dedup 게이트가 INVALID 를
    종단으로 취급해서(purchase.py) 나중에 시크릿을 넣어도 그 구매는 영영 지급되지 않는다.
    """
    return bool(host and client_id and client_secret)


def _normalize_host(host: str) -> str:
    # 사람이 손으로 시크릿에 넣는 값이라 끝에 / 가 붙어 오기 쉽다. 그대로 두면 `//v7/...`.
    return host.rstrip("/")


def _error_detail(resp: requests.Response) -> str:
    """원스토어 표준 오류 본문 `{"error": {"code", "message"}}` 를 사람이 읽을 문자열로."""
    try:
        error = resp.json().get("error") or {}
        code, message = error.get("code"), error.get("message")
        if code or message:
            return f"{code}: {message}"
    except Exception:  # noqa: BLE001 - 본문이 JSON 이 아닐 수도 있다
        pass
    # 원스토어 앱까지 못 간 응답(프론트 서버의 HTML 404 등). 본문을 그대로 영수증 msg 에
    #   넣으면 HTML 덩어리가 들어가 읽을 수 없다 — 성격만 남긴다.
    return f"HTTP {resp.status_code} (non-JSON — 원스토어 앱에 도달하지 못한 응답)"


def _state_name(enum_cls, value: int) -> str:
    """모르는 값이 와도 CS 가 읽을 수 있는 문구로. `Malformed` 로 묻지 않기 위해."""
    try:
        return enum_cls(value).name
    except ValueError:
        return f"UNKNOWN({value})"


def _issue_access_token(
    host: str, client_id: str, client_secret: str
) -> Tuple[Optional[str], int, str]:
    """(token, expires_in, error_message)."""
    try:
        resp = requests.post(
            f"{host}/v7/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=HTTP_TIMEOUT,
        )
    except requests.RequestException as e:
        return None, 0, f"Failed to get ONE Store access token: {e}"

    if resp.status_code != 200:
        return None, 0, f"Failed to get ONE Store access token: {_error_detail(resp)}"

    try:
        body = resp.json()
        return str(body["access_token"]), int(body["expires_in"]), ""
    except Exception as e:  # noqa: BLE001
        return None, 0, f"Malformed ONE Store access token response: {e}"


def get_access_token(
    host: str, client_id: str, client_secret: str, force_refresh: bool = False
) -> Tuple[Optional[str], str]:
    """캐시된 토큰을 주거나 새로 받아 온다. 반환: (token, error_message).

    ⚠️ `force_refresh` 가 실제로 **새** 토큰을 주는지는 미검증이다. 문서가 "만료됐거나 600초
       미만 남은 경우 신규 발급 가능" 이라고만 해서, 잔여가 많은데 401 을 맞은 상황이면 같은
       (죽은) 토큰을 돌려받아 재시도가 무의미해질 수 있다. 샌드박스에서 한 번 확인할 것.
    """
    host = _normalize_host(host)
    key = (host, client_id)
    if not force_refresh:
        with _token_lock:
            cached = _token_cache.get(key)
        # 잔여가 마진보다 많을 때만 재사용한다.
        if cached and cached[1] - time.monotonic() > TOKEN_REFRESH_MARGIN:
            return cached[0], ""

    # HTTP 는 락 밖에서 한다. 동시 요청이 겹쳐 두 번 발급되는 건 무해하다
    # (원스토어가 유효한 토큰을 돌려주므로 값이 같거나, 달라도 둘 다 유효하다).
    token, expires_in, msg = _issue_access_token(host, client_id, client_secret)
    if token is None:
        return None, msg

    with _token_lock:
        _token_cache[key] = (token, time.monotonic() + expires_in)
    return token, ""


def _unqueryable_reason(product_id: str, purchase_token: str) -> Optional[str]:
    """조회 자체가 불가능한 입력인지. 불가능하면 사람이 읽을 이유를 돌려준다.

    2026-09-02 샌드박스 실측: 경로 세그먼트에 **`%2F` 만** 원스토어 프론트 서버가 HTML 404
    로 거부한다(Apache `AllowEncodedSlashes Off` 로 보인다). `%2B` `%3D` `%25` `%2E%2E` 는
    전부 원스토어 앱까지 도달해 정상 JSON 오류(`NoSuchData`)를 받는다 — 즉 인코딩은
    필요하고 옳다(`%2E%2E` 가 `..` 로 정규화되지 않는 것도 확인했다).

    따라서 `/` 가 든 purchaseToken 은 **원스토어 자신의 엔드포인트로도 주소를 지정할 수
    없다.** 실제 토큰에 `/` 가 안 들어온다는 뜻이지만, 들어오면 HTML 404 를 "구매 없음"
    으로 오해하게 되므로 여기서 끊는다.
    """
    for label, value in (("productId", product_id), ("purchaseToken", purchase_token)):
        if "/" in value:
            return f"{label} contains '/', which ONE Store's own endpoint cannot address"
    return None


def _purchase_url(host: str, client_id: str, product_id: str, purchase_token: str) -> str:
    # purchaseToken 은 URL 경로에 들어가는데 `/` `+` `=` 가 섞여 나온다. 그대로 붙이면
    # 경로가 갈라져 엉뚱한 엔드포인트를 친다. safe="" 로 슬래시까지 인코딩한다.
    return (
        f"{_normalize_host(host)}/v7/apps/{urllib.parse.quote(client_id, safe='')}"
        f"/purchases/inapp/products/{urllib.parse.quote(product_id, safe='')}"
        f"/{urllib.parse.quote(purchase_token, safe='')}"
    )


def _fetch_purchase(
    host: str,
    client_id: str,
    client_secret: str,
    product_id: str,
    purchase_token: str,
) -> Tuple[Optional[requests.Response], str]:
    """구매 조회. 최대 2회 시도한다.

    재시도하는 경우는 둘뿐이고 서로 배타적이다(합쳐서 늘어나지 않는다):
      - 401  : 캐시한 토큰이 서버에서 먼저 죽음 → 강제 재발급 후 1회
      - 5xx/네트워크 : 원스토어 일시 장애 → 그대로 1회 (apple.py 선례)
    나머지(404 NoSuchData 등)는 영수증 자체의 문제라 재시도해도 같은 답이다.
    """
    unqueryable = _unqueryable_reason(product_id, purchase_token)
    if unqueryable is not None:
        return None, f"Error occurred validating ONE Store receipt: {unqueryable}"

    access_token, msg = get_access_token(host, client_id, client_secret)
    if access_token is None:
        return None, msg

    url = _purchase_url(host, client_id, product_id, purchase_token)
    last_error = ""
    for attempt in (1, 2):
        try:
            resp = requests.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=HTTP_TIMEOUT,
            )
        except requests.RequestException as e:
            last_error = f"Error occurred validating ONE Store receipt: {e}"
            if attempt == 2:
                return None, last_error
            continue

        if attempt == 2 or (resp.status_code != 401 and resp.status_code < 500):
            return resp, ""

        if resp.status_code == 401:
            access_token, msg = get_access_token(
                host, client_id, client_secret, force_refresh=True
            )
            if access_token is None:
                return None, msg
        last_error = _error_detail(resp)

    # 도달하지 않는다(위 루프가 attempt==2 에서 반드시 반환한다).
    return None, last_error


def validate_onestore(
    host: str,
    client_id: str,
    client_secret: str,
    product_id: str,
    purchase_token: str,
    purchase_id: str,
) -> Tuple[bool, str, Optional[OneStorePurchaseSchema]]:
    """구매를 원스토어에 물어서 확인한다.

    :param host: 배포별 원스토어 호스트(검증 sbpp / 상용 iap-apis)
    :param purchase_id: 영수증이 주장하는 `purchaseId`. 응답과 대조한다.
    :return: (성공여부, 실패사유, 조회결과)

    실패해도 조회 결과가 있으면 같이 돌려준다 — 호출자가 상태를 영수증에 남길 수 있게.
    """
    if not is_onestore_configured(host, client_id, client_secret):
        # 시크릿 배선 전에는 "검증 통과"가 아니라 거절이어야 한다. 다만 호출자는 여기까지
        # 오기 전에 `is_onestore_configured` 로 걸러야 한다(그 함수 주석 참조).
        return False, "ONE Store credentials are not configured", None

    resp, msg = _fetch_purchase(
        host, client_id, client_secret, product_id, purchase_token
    )
    if resp is None:
        return False, msg, None

    if resp.status_code != 200:
        # 상용 호스트에 샌드박스 구매를 물으면 NoSuchData(404) 로 여기 떨어진다.
        # 토큰과 맞지 않는 productId 로 물어도 여기다 — 상품 치환을 막는 유일한 방어선.
        return (
            False,
            f"Error occurred validating ONE Store receipt: {_error_detail(resp)}",
            None,
        )

    try:
        purchase = OneStorePurchaseSchema(**resp.json())
    except Exception as e:  # noqa: BLE001
        return False, f"Malformed ONE Store purchase data: {e}", None

    if purchase.purchaseState != OneStorePurchaseState.PURCHASED:
        return (
            False,
            "Purchase state of this receipt is not valid: "
            f"{_state_name(OneStorePurchaseState, purchase.purchaseState)}",
            purchase,
        )

    # 영수증이 주장하는 구매와 토큰이 가리키는 구매가 같은지. 응답에 productId/orderId 가
    # 없어서 대조할 수 있는 건 이것뿐이다.
    if purchase.purchaseId != purchase_id:
        return (
            False,
            f"Purchase ID mismatch from request and token: "
            f"{purchase_id} :: {purchase.purchaseId}",
            purchase,
        )

    # 이미 소비된 구매 = 이미 지급한 구매다(클라이언트는 배송 확정 뒤에만 소비한다).
    #   정상 흐름이면 (store, order_id) dedup 이 먼저 잡지만, 영수증 행이 없는 상태에서
    #   같은 토큰이 다시 오는 경우(복원·환경 혼선)의 2선 방어다.
    if purchase.consumptionState == OneStoreConsumptionState.CONSUMED:
        return (
            False,
            "This purchase has already been consumed",
            purchase,
        )

    # 수량 구매는 지급 경로가 없다(영수증 1건 = 상품 1개). 클라이언트가 수량을 지정하지
    #   않아 실제로는 항상 1 이지만, 2 가 오면 조용히 덜 주는 대신 거절한다.
    if purchase.quantity != 1:
        return (
            False,
            f"Multi-quantity ONE Store purchase is not supported: "
            f"quantity={purchase.quantity}",
            purchase,
        )

    return True, "", purchase


def acknowledge_onestore(
    host: str,
    client_id: str,
    client_secret: str,
    product_id: str,
    purchase_token: str,
) -> Tuple[bool, str]:
    """구매확인(acknowledge). **지급을 내보낸 뒤에만** 부를 것.

    원스토어는 3일 안에 소비/승인되지 않은 구매를 자동 환불한다. 정상 흐름에서는
    클라이언트가 배송 확정 후 consume 해서 그 창이 닫히지만, consume 을 안 하면(앱을 죽이거나
    호출을 막으면) **지급은 나갔는데 결제만 사라진다.** 그 구멍을 서버가 닫는다.

    Google 의 `ack_google` 과 달리 검증 직후가 아니라 **배송 뒤**에 부른다. 검증 직후에
    닫아 버리면 지급이 실패한 건까지 환불이 막혀서 산 사람이 아무것도 못 받는다.

    실패해도 지급은 이미 나갔으므로 예외를 올리지 않는다. 호출자가 로그만 남긴다.
    """
    if not is_onestore_configured(host, client_id, client_secret):
        return False, "ONE Store credentials are not configured"

    unqueryable = _unqueryable_reason(product_id, purchase_token)
    if unqueryable is not None:
        return False, f"Failed to acknowledge ONE Store purchase: {unqueryable}"

    access_token, msg = get_access_token(host, client_id, client_secret)
    if access_token is None:
        return False, msg

    # 조회는 `purchases/inapp/...`, 확인은 `purchases/all/...` 이다(문서 그대로).
    url = (
        f"{_normalize_host(host)}/v7/apps/{urllib.parse.quote(client_id, safe='')}"
        f"/purchases/all/products/{urllib.parse.quote(product_id, safe='')}"
        f"/{urllib.parse.quote(purchase_token, safe='')}/acknowledge"
    )
    try:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=HTTP_TIMEOUT,
        )
    except requests.RequestException as e:
        return False, f"Failed to acknowledge ONE Store purchase: {e}"

    if resp.status_code != 200:
        return False, f"Failed to acknowledge ONE Store purchase: {_error_detail(resp)}"
    return True, ""
