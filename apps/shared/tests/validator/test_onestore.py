"""원스토어 구매 검증기.

문서: https://onestore-dev.gitbook.io/dev/tools/billing/v21/serverapi
"""

import json
from unittest.mock import Mock, patch

import pytest

from shared.enums import OneStoreConsumptionState, OneStorePurchaseState
from shared.validator import onestore as onestore_validator
from shared.validator.onestore import acknowledge_onestore, validate_onestore

HOST = "https://sbpp.onestore.net"
CLIENT_ID = "0000000001"
CLIENT_SECRET = "s3cr3t"
PRODUCT_ID = "g_pkg_worldclearpass1premium"
TOKEN = "purchase.token+with=special%chars"
PURCHASE_ID = "17070421461015116878"

TOKEN_BODY = {
    "client_id": CLIENT_ID,
    "access_token": "680b3621-1234-1234-1234-8adfaef561b4",
    "token_type": "bearer",
    "expires_in": 3600,
    "scope": "DEFAULT",
}
PURCHASE_BODY = {
    "consumptionState": 0,
    "developerPayload": "",
    "purchaseState": 0,
    "purchaseTime": 1756800000000,
    "purchaseId": PURCHASE_ID,
    "acknowledgeState": 0,
    "quantity": 1,
}


def _resp(status: int, body) -> Mock:
    resp = Mock()
    resp.status_code = status
    resp.json.return_value = body
    resp.text = json.dumps(body)
    return resp


@pytest.fixture(autouse=True)
def clear_token_cache():
    onestore_validator.clear_token_cache()
    yield
    onestore_validator.clear_token_cache()


def _call(**overrides):
    kwargs = dict(
        host=HOST,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        product_id=PRODUCT_ID,
        purchase_token=TOKEN,
        purchase_id=PURCHASE_ID,
    )
    kwargs.update(overrides)
    return validate_onestore(**kwargs)


class TestValidateOneStore:
    def test_valid_purchase(self):
        with patch.object(
            onestore_validator.requests, "post", return_value=_resp(200, TOKEN_BODY)
        ), patch.object(
            onestore_validator.requests, "get", return_value=_resp(200, PURCHASE_BODY)
        ):
            success, msg, purchase = _call()

        assert success is True
        assert msg == ""
        assert purchase.purchaseId == PURCHASE_ID
        assert purchase.purchaseState == OneStorePurchaseState.PURCHASED
        assert purchase.consumptionState == OneStoreConsumptionState.YET_BE_CONSUMED

    def test_request_shape(self):
        """토큰 발급·구매 조회 요청이 문서 규격대로 나가야 한다."""
        post = Mock(return_value=_resp(200, TOKEN_BODY))
        get = Mock(return_value=_resp(200, PURCHASE_BODY))
        with patch.object(onestore_validator.requests, "post", post), patch.object(
            onestore_validator.requests, "get", get
        ):
            _call()

        assert post.call_args.args[0] == f"{HOST}/v7/oauth/token"
        assert post.call_args.kwargs["data"] == {
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        }

        url = get.call_args.args[0]
        assert url.startswith(f"{HOST}/v7/apps/{CLIENT_ID}/purchases/inapp/products/")
        # purchaseToken 에 + = % 가 섞여 온다. 인코딩해야 경로가 안 깨진다.
        #   2026-09-02 샌드박스 실측: %2B %3D %25 %2E%2E 는 전부 원스토어 앱까지 도달한다.
        assert "purchase.token+with=special%chars" not in url
        assert "purchase.token%2Bwith%3Dspecial%25chars" in url
        headers = get.call_args.kwargs["headers"]
        assert headers["Authorization"] == f"Bearer {TOKEN_BODY['access_token']}"
        # 🔴 x-market-code 가 없으면 원스토어가 한국 마켓에서 조회해 모든 구매가
        #    NoSuchData 로 보인다(2026-09-02 실측: 헤더없음/MKT_ONE=404, MKT_GLB=200).
        assert headers["x-market-code"] == "MKT_GLB"
        assert headers["Content-Type"] == "application/json"

    def test_canceled_purchase_is_rejected(self):
        body = {**PURCHASE_BODY, "purchaseState": OneStorePurchaseState.CANCELED.value}
        with patch.object(
            onestore_validator.requests, "post", return_value=_resp(200, TOKEN_BODY)
        ), patch.object(
            onestore_validator.requests, "get", return_value=_resp(200, body)
        ):
            success, msg, purchase = _call()

        assert success is False
        assert "CANCELED" in msg
        assert purchase is not None  # 호출자가 상태를 기록할 수 있어야 한다

    def test_purchase_id_mismatch_is_rejected(self):
        """다른 구매의 토큰을 자기 영수증에 붙여 보내는 경우."""
        body = {**PURCHASE_BODY, "purchaseId": "99999999999999999999"}
        with patch.object(
            onestore_validator.requests, "post", return_value=_resp(200, TOKEN_BODY)
        ), patch.object(
            onestore_validator.requests, "get", return_value=_resp(200, body)
        ):
            success, msg, _ = _call()

        assert success is False
        assert "mismatch" in msg.lower()

    def test_unknown_purchase_is_rejected(self):
        """상용 호스트에 샌드박스 구매를 물으면 여기로 떨어진다(NoSuchData/404)."""
        err = {"error": {"code": "NoSuchData", "message": "no such data"}}
        with patch.object(
            onestore_validator.requests, "post", return_value=_resp(200, TOKEN_BODY)
        ), patch.object(
            onestore_validator.requests, "get", return_value=_resp(404, err)
        ):
            success, msg, purchase = _call()

        assert success is False
        assert "NoSuchData" in msg
        assert purchase is None

    def test_token_issue_failure_is_rejected(self):
        err = {"error": {"code": "InvalidClient", "message": "bad client"}}
        with patch.object(
            onestore_validator.requests, "post", return_value=_resp(401, err)
        ):
            success, msg, purchase = _call()

        assert success is False
        assert "access token" in msg.lower()
        assert purchase is None

    @pytest.mark.parametrize("empty", [None, ""])
    @pytest.mark.parametrize("missing", ["host", "client_id", "client_secret"])
    def test_missing_config_fails_closed(self, missing, empty):
        """시크릿 배선 전에는 지급이 아니라 거절로 끝나야 한다.

        실제 미배선 값은 `None`(config 기본값)이고, 빈 문자열로 들어올 수도 있다.
        """
        success, msg, purchase = _call(**{missing: empty})

        assert success is False
        assert "not configured" in msg
        assert purchase is None

    def test_consumed_purchase_is_rejected(self):
        """이미 소비된 구매 = 이미 지급한 구매. dedup 이 놓쳤을 때의 2선 방어."""
        body = {**PURCHASE_BODY, "consumptionState": OneStoreConsumptionState.CONSUMED.value}
        with patch.object(
            onestore_validator.requests, "post", return_value=_resp(200, TOKEN_BODY)
        ), patch.object(
            onestore_validator.requests, "get", return_value=_resp(200, body)
        ):
            success, msg, _ = _call()

        assert success is False
        assert "already been consumed" in msg

    def test_multi_quantity_is_rejected(self):
        """지급 경로가 영수증 1건 = 상품 1개다. 조용히 덜 주는 대신 거절한다."""
        with patch.object(
            onestore_validator.requests, "post", return_value=_resp(200, TOKEN_BODY)
        ), patch.object(
            onestore_validator.requests,
            "get",
            return_value=_resp(200, {**PURCHASE_BODY, "quantity": 2}),
        ):
            success, msg, _ = _call()

        assert success is False
        assert "quantity=2" in msg

    def test_unknown_purchase_state_is_named_not_malformed(self):
        """문서에 없는 상태값이 와도 CS 가 원인을 오해하지 않게."""
        with patch.object(
            onestore_validator.requests, "post", return_value=_resp(200, TOKEN_BODY)
        ), patch.object(
            onestore_validator.requests,
            "get",
            return_value=_resp(200, {**PURCHASE_BODY, "purchaseState": 7}),
        ):
            success, msg, purchase = _call()

        assert success is False
        assert "UNKNOWN(7)" in msg
        assert "Malformed" not in msg
        assert purchase is not None

    def test_null_developer_payload_is_accepted(self):
        """상용은 `developerPayload` 를 **null** 로 준다 — 검증환경은 `""` 를 준다.

        필드 기본값은 키가 **없을 때만** 먹고 명시적 null 에는 안 먹는다. 그대로 두면
        상용 구매가 전부 `Malformed ONE Store purchase data` 로 떨어져 INVALID 로 굳는다.
        샌드박스에서는 절대 안 잡히는 차이라, 2026-09-21 인터널 호스트를 상용으로 돌려
        실측했다(구매 26091804355110440543).
        """
        with patch.object(
            onestore_validator.requests, "post", return_value=_resp(200, TOKEN_BODY)
        ), patch.object(
            onestore_validator.requests,
            "get",
            return_value=_resp(200, {**PURCHASE_BODY, "developerPayload": None}),
        ):
            success, msg, purchase = _call()

        assert success is True, msg
        assert purchase.developerPayload is None

    def test_host_trailing_slash_is_normalized(self):
        get = Mock(return_value=_resp(200, PURCHASE_BODY))
        with patch.object(
            onestore_validator.requests, "post", return_value=_resp(200, TOKEN_BODY)
        ), patch.object(onestore_validator.requests, "get", get):
            _call(host=HOST + "/")

        assert "//v7/" not in get.call_args.args[0]

    def test_server_error_is_retried_once(self):
        """원스토어 일시 장애. 실패하면 영수증이 INVALID 로 굳어 복구가 안 되므로 한 번은 더."""
        get = Mock(side_effect=[_resp(503, {}), _resp(200, PURCHASE_BODY)])
        with patch.object(
            onestore_validator.requests, "post", return_value=_resp(200, TOKEN_BODY)
        ), patch.object(onestore_validator.requests, "get", get):
            success, msg, _ = _call()

        assert success is True, msg
        assert get.call_count == 2

    def test_server_error_twice_gives_up(self):
        get = Mock(return_value=_resp(503, {}))
        with patch.object(
            onestore_validator.requests, "post", return_value=_resp(200, TOKEN_BODY)
        ), patch.object(onestore_validator.requests, "get", get):
            success, msg, purchase = _call()

        assert success is False
        assert get.call_count == 2
        assert purchase is None

    def test_market_code_is_overridable(self):
        """배포국가가 한국이면 MKT_ONE 이다. 코드 수정 없이 바꿀 수 있어야 한다."""
        get = Mock(return_value=_resp(200, PURCHASE_BODY))
        with patch.object(
            onestore_validator.requests, "post", return_value=_resp(200, TOKEN_BODY)
        ), patch.object(onestore_validator.requests, "get", get):
            _call(market_code="MKT_ONE")

        assert get.call_args.kwargs["headers"]["x-market-code"] == "MKT_ONE"

    def test_not_found_message_names_the_market(self):
        """마켓 오설정이면 모든 구매가 NoSuchData 로 떨어진다 — 어디로 물었는지 남긴다."""
        err = {"error": {"code": "NoSuchData", "message": "no such data"}}
        with patch.object(
            onestore_validator.requests, "post", return_value=_resp(200, TOKEN_BODY)
        ), patch.object(
            onestore_validator.requests, "get", return_value=_resp(404, err)
        ):
            success, msg, _ = _call(market_code="MKT_ONE")

        assert success is False
        assert "NoSuchData" in msg
        assert "market=MKT_ONE" in msg

    def test_slash_in_token_is_rejected_without_calling(self):
        """`/` 가 든 토큰은 원스토어 프론트 서버가 HTML 404 로 끊는다(실측).

        그 응답을 "구매 없음" 으로 오해하면 안 되므로 부르기 전에 끊는다.
        """
        post = Mock(return_value=_resp(200, TOKEN_BODY))
        get = Mock()
        with patch.object(onestore_validator.requests, "post", post), patch.object(
            onestore_validator.requests, "get", get
        ):
            success, msg, purchase = _call(purchase_token="tok/with/slash")

        assert success is False
        assert "cannot address" in msg
        assert purchase is None
        assert get.call_count == 0  # 무의미한 왕복을 하지 않는다
        assert post.call_count == 0

    def test_non_json_error_body_is_summarized(self):
        """HTML 응답 본문을 영수증 msg 에 그대로 넣지 않는다."""
        html = Mock()
        html.status_code = 404
        html.json.side_effect = ValueError("not json")
        html.text = "<!DOCTYPE HTML><html><head><title>404 Not Found</title></head></html>"
        with patch.object(
            onestore_validator.requests, "post", return_value=_resp(200, TOKEN_BODY)
        ), patch.object(onestore_validator.requests, "get", return_value=html):
            success, msg, _ = _call()

        assert success is False
        assert "DOCTYPE" not in msg
        assert "non-JSON" in msg

    def test_not_found_is_not_retried(self):
        """404 는 영수증 자체의 문제다 — 다시 물어도 같은 답이라 락을 더 잡을 이유가 없다."""
        get = Mock(return_value=_resp(404, {"error": {"code": "NoSuchData", "message": "x"}}))
        with patch.object(
            onestore_validator.requests, "post", return_value=_resp(200, TOKEN_BODY)
        ), patch.object(onestore_validator.requests, "get", get):
            success, _, _ = _call()

        assert success is False
        assert get.call_count == 1

    def test_network_error_is_rejected(self):
        get = Mock(side_effect=onestore_validator.requests.RequestException("boom"))
        with patch.object(
            onestore_validator.requests, "post", return_value=_resp(200, TOKEN_BODY)
        ), patch.object(onestore_validator.requests, "get", get):
            success, msg, purchase = _call()

        assert success is False
        assert "boom" in msg
        assert purchase is None
        assert get.call_count == 2  # 네트워크 오류도 한 번은 더 시도한다

    def test_malformed_body_is_rejected(self):
        with patch.object(
            onestore_validator.requests, "post", return_value=_resp(200, TOKEN_BODY)
        ), patch.object(
            onestore_validator.requests, "get", return_value=_resp(200, {"nope": 1})
        ):
            success, msg, purchase = _call()

        assert success is False
        assert "malformed" in msg.lower()
        assert purchase is None


class TestAccessTokenCache:
    def test_token_is_reused(self):
        post = Mock(return_value=_resp(200, TOKEN_BODY))
        get = Mock(return_value=_resp(200, PURCHASE_BODY))
        with patch.object(onestore_validator.requests, "post", post), patch.object(
            onestore_validator.requests, "get", get
        ):
            _call()
            _call()

        assert post.call_count == 1
        assert get.call_count == 2

    def test_token_near_expiry_is_reissued(self):
        """문서상 잔여 600초 미만이면 재발급 대상."""
        post = Mock(return_value=_resp(200, {**TOKEN_BODY, "expires_in": 300}))
        get = Mock(return_value=_resp(200, PURCHASE_BODY))
        with patch.object(onestore_validator.requests, "post", post), patch.object(
            onestore_validator.requests, "get", get
        ):
            _call()
            _call()

        assert post.call_count == 2

    def test_expired_token_is_reissued_and_retried_once(self):
        """캐시된 토큰이 서버에서 먼저 죽은 경우 — 401 한 번은 스스로 회복한다."""
        expired = _resp(401, {"error": {"code": "AccessTokenExpired", "message": "expired"}})
        post = Mock(return_value=_resp(200, TOKEN_BODY))
        get = Mock(side_effect=[expired, _resp(200, PURCHASE_BODY)])
        with patch.object(onestore_validator.requests, "post", post), patch.object(
            onestore_validator.requests, "get", get
        ):
            success, msg, purchase = _call()

        assert success is True, msg
        assert get.call_count == 2
        assert post.call_count == 2  # 최초 발급 + 401 후 재발급

    def test_repeated_401_gives_up(self):
        expired = _resp(401, {"error": {"code": "AccessTokenExpired", "message": "expired"}})
        post = Mock(return_value=_resp(200, TOKEN_BODY))
        get = Mock(return_value=expired)
        with patch.object(onestore_validator.requests, "post", post), patch.object(
            onestore_validator.requests, "get", get
        ):
            success, msg, purchase = _call()

        assert success is False
        assert get.call_count == 2
        assert "AccessTokenExpired" in msg

    def test_cache_is_per_host(self):
        """인터널(sbpp)과 메인넷(iap-apis) 토큰이 섞이면 안 된다."""
        post = Mock(return_value=_resp(200, TOKEN_BODY))
        get = Mock(return_value=_resp(200, PURCHASE_BODY))
        with patch.object(onestore_validator.requests, "post", post), patch.object(
            onestore_validator.requests, "get", get
        ):
            _call()
            _call(host="https://iap-apis.onestore.net")

        assert post.call_count == 2


class TestAcknowledge:
    """지급 뒤 구매확인. 클라이언트가 consume 을 안 해도 3일 자동환불 창을 닫는다."""

    def test_acknowledge_uses_all_products_path(self):
        post = Mock(
            side_effect=[_resp(200, TOKEN_BODY), _resp(200, {})]
        )
        with patch.object(onestore_validator.requests, "post", post):
            ok, msg = acknowledge_onestore(
                HOST, CLIENT_ID, CLIENT_SECRET, PRODUCT_ID, TOKEN
            )

        assert ok is True, msg
        url = post.call_args.args[0]
        # 조회는 purchases/inapp, 확인은 purchases/all 이다.
        assert url.startswith(f"{HOST}/v7/apps/{CLIENT_ID}/purchases/all/products/")
        assert url.endswith("/acknowledge")
        assert "purchase.token%2Bwith%3Dspecial%25chars" in url
        # 조회와 같은 마켓으로 승인해야 한다 — 안 그러면 승인이 안 먹고 자동환불된다.
        assert post.call_args.kwargs["headers"]["x-market-code"] == "MKT_GLB"

    def test_acknowledge_failure_is_reported_not_raised(self):
        post = Mock(
            side_effect=[
                _resp(200, TOKEN_BODY),
                _resp(409, {"error": {"code": "InvalidPurchaseState", "message": "x"}}),
            ]
        )
        with patch.object(onestore_validator.requests, "post", post):
            ok, msg = acknowledge_onestore(
                HOST, CLIENT_ID, CLIENT_SECRET, PRODUCT_ID, TOKEN
            )

        assert ok is False
        assert "InvalidPurchaseState" in msg

    def test_acknowledge_without_config_is_reported(self):
        ok, msg = acknowledge_onestore("", "", "", PRODUCT_ID, TOKEN)

        assert ok is False
        assert "not configured" in msg


# --- 호스트 분기 (PLD-1616) --------------------------------------------------
#
# 한 배포가 샌드박스와 상용을 **둘 다** 처리해야 하는 경우가 있다. 검증요청 잠금은 샌드박스
# 결제를, 심사자는 상용 결제를 요구한다. 다만 이건 fail-closed 장치를 여는 것이라, 설정하지
# 않은 배포(메인넷)에서는 종전 동작이 그대로여야 한다.

from shared.validator.onestore import (
    is_sandbox_token,
    resolve_host,
    warn_if_sandbox_host_on_prod,
)

SANDBOX = "https://sbpp.onestore.net"
PROD = "https://iap-apis.onestore.net"

# 실측값 (2026-09-21)
SANDBOX_TOKEN = "SANDBOX3000002616574"
PROD_TOKEN = "260918043551SGP40543"


def test_is_sandbox_token():
    assert is_sandbox_token(SANDBOX_TOKEN)
    assert not is_sandbox_token(PROD_TOKEN)
    assert not is_sandbox_token("")
    assert not is_sandbox_token(None)


def test_resolve_host_without_sandbox_host_is_unchanged():
    """샌드박스 호스트를 설정하지 않으면 종전 그대로 — 메인넷의 fail-closed 가 유지된다."""
    assert resolve_host(PROD, None, SANDBOX_TOKEN, False) == PROD
    assert resolve_host(PROD, None, PROD_TOKEN, False) == PROD
    assert resolve_host(SANDBOX, None, PROD_TOKEN, False) == SANDBOX


def test_resolve_host_routes_by_token_when_configured():
    """설정한 배포에서만 토큰을 보고 갈린다."""
    assert resolve_host(PROD, SANDBOX, SANDBOX_TOKEN, False) == SANDBOX
    assert resolve_host(PROD, SANDBOX, PROD_TOKEN, False) == PROD


def test_resolve_host_passes_through_none_host():
    assert resolve_host(None, SANDBOX, PROD_TOKEN, False) is None


# `is_prod` 가드. 예전엔 "메인넷엔 설정하지 않는다" 는 **관례**뿐이었고, 그 관례는 지킬 수단이
# 없었다 — 차트가 양쪽에 같은 템플릿을 렌더하고 메인넷/인터널을 가르는 건 시크릿 JSON 에 키가
# 있느냐 하나인데, 그 JSON 은 통째로 읽어 병합해 되쓴다. 키가 딸려 들어가도 **무증상**이고
# 결과는 공짜 샌드박스 구매의 실지급(+ NCG 바우처)이다. 그래서 코드가 막는다.
def test_prod_ignores_sandbox_host_even_for_sandbox_token():
    """메인넷에선 설정이 들어와 있어도 샌드박스 호스트로 가지 않는다 — 이게 방어의 핵심이다."""
    assert resolve_host(PROD, SANDBOX, SANDBOX_TOKEN, True) == PROD
    assert resolve_host(PROD, SANDBOX, PROD_TOKEN, True) == PROD
    # 호스트가 아예 없으면 그대로 None (설정 누락은 여기서 만들어내지 않는다).
    assert resolve_host(None, SANDBOX, SANDBOX_TOKEN, True) is None


def test_warn_fires_only_on_prod_with_sandbox_host():
    """무시하는 것과 별개로, 설정이 잘못 들어왔다는 **사실 자체**는 신호라 기동 시 찍는다."""

    class _Log:
        def __init__(self):
            self.errors = []

        def error(self, msg):
            self.errors.append(msg)

    log = _Log()
    assert warn_if_sandbox_host_on_prod(SANDBOX, True, log) is True
    assert len(log.errors) == 1
    assert "ONESTORE_SANDBOX_HOST_ON_PROD" in log.errors[0]

    # 나머지 세 조합은 조용해야 한다(인터널의 정상 설정에 알람이 울리면 안 된다).
    quiet = _Log()
    assert warn_if_sandbox_host_on_prod(SANDBOX, False, quiet) is False
    assert warn_if_sandbox_host_on_prod(None, True, quiet) is False
    assert warn_if_sandbox_host_on_prod(None, False, quiet) is False
    assert quiet.errors == []
