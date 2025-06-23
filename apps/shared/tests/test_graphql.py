import pytest

from common._graphql import GQL
from iap import settings


@pytest.mark.parametrize("headless", [
    "https://odin-rpc.nine-chronicles.com/graphql",
    "https://heimdall-rpc.nine-chronicles.com/graphql",
])
def test_gql_jwt(headless):
    gql = GQL(headless, settings.HEADLESS_JWT_GQL_SECRET)
    test_nonce = gql.get_next_nonce("0x0000000000000000000000000000000000000000")
    assert test_nonce == 0
