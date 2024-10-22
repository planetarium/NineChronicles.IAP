import os

import pytest

from common.utils.address import format_addr, get_vault_agent_address, get_vault_avatar_address
from common.utils.receipt import PlanetID


@pytest.mark.parametrize("address", [
    "dde23c49C0e36B5f8206Dbdac60675288484B37E",
    "0xdde23c49C0e36B5f8206Dbdac60675288484B37E"
])
def test_format_addr(address: str):
    expected = "0xdde23c49C0e36B5f8206Dbdac60675288484B37E".lower()
    assert format_addr(address) == expected


@pytest.mark.parametrize("planet_id, key", [
    (PlanetID.ODIN, "ODIN_AGENT_ADDRESS"),
    (PlanetID.HEIMDALL, "HEIMDALL_AGENT_ADDRESS"),
    (PlanetID.ODIN_INTERNAL, "ODIN_INTERNAL_AGENT_ADDRESS"),
    (PlanetID.HEIMDALL_INTERNAL, "HEIMDALL_INTERNAL_AGENT_ADDRESS"),
])
def test_get_vault_agent_address(planet_id: PlanetID, key: str):
    os.environ[key] = "dde23c49C0e36B5f8206Dbdac60675288484B37E"
    assert get_vault_agent_address(planet_id) == "0xdde23c49C0e36B5f8206Dbdac60675288484B37E".lower()


@pytest.mark.parametrize("planet_id, key", [
    (PlanetID.ODIN, "ODIN_AVATAR_ADDRESS"),
    (PlanetID.HEIMDALL, "HEIMDALL_AVATAR_ADDRESS"),
    (PlanetID.ODIN_INTERNAL, "ODIN_INTERNAL_AVATAR_ADDRESS"),
    (PlanetID.HEIMDALL_INTERNAL, "HEIMDALL_INTERNAL_AVATAR_ADDRESS"),
])
def test_get_vault_avatar_address(planet_id: PlanetID, key: str):
    os.environ[key] = "dde23c49C0e36B5f8206Dbdac60675288484B37E"
    assert get_vault_avatar_address(planet_id) == "0xdde23c49C0e36B5f8206Dbdac60675288484B37E".lower()

