import pytest

from common.utils.address import format_addr, derive_vault_address
from common.utils.receipt import PlanetID


@pytest.mark.parametrize("address", [
    "dde23c49C0e36B5f8206Dbdac60675288484B37E",
    "0xdde23c49C0e36B5f8206Dbdac60675288484B37E"
])
def test_format_addr(address: str):
    expected = "0xdde23c49C0e36B5f8206Dbdac60675288484B37E"
    assert format_addr(address) == expected


@pytest.mark.parametrize("planet_id, address", [
    (PlanetID.ODIN, "c727838fca8bfaf557cd6186388abdc9292c1524"),
    (PlanetID.HEIMDALL, "54e54f755282f4f2742f1a362469a7ff2f9300ae"),
])
def test_derive_vault_address(planet_id: PlanetID, address: str):
    assert derive_vault_address(planet_id).hex() == address
