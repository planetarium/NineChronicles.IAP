import pytest
from unittest.mock import Mock

from shared._graphql import GQL


@pytest.mark.parametrize("headless", [
    "https://odin-rpc.nine-chronicles.com/graphql",
    "https://heimdall-rpc.nine-chronicles.com/graphql",
])
def test_gql_jwt(headless):
    # 테스트용 JWT 시크릿
    jwt_secret = "test_secret"
    gql = GQL(headless, jwt_secret)
    test_nonce = gql.get_next_nonce("0x0000000000000000000000000000000000000000")
    assert test_nonce == 0
