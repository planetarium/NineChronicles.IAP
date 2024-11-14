import pytest

from common.utils.address import format_addr


@pytest.mark.parametrize("address", [
    "dde23c49C0e36B5f8206Dbdac60675288484B37E",
    "0xdde23c49C0e36B5f8206Dbdac60675288484B37E"
])
def test_format_addr(address: str):
    expected = "0xdde23c49C0e36B5f8206Dbdac60675288484B37E".lower()
    assert format_addr(address) == expected
