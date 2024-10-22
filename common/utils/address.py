import os

from common.utils.receipt import PlanetID


def format_addr(addr: str) -> str:
    """
    Check and reformat input address if not starts with `0x`.
    """
    if not addr.startswith("0x"):
        addr = f"0x{addr}"
    return addr.lower()


def get_vault_agent_address(planet_id: PlanetID) -> str:
    if planet_id == PlanetID.ODIN:
        address = os.environ["ODIN_AGENT_ADDRESS"]
    elif planet_id == PlanetID.HEIMDALL:
        address = os.environ["HEIMDALL_AGENT_ADDRESS"]
    elif planet_id == PlanetID.ODIN_INTERNAL:
        address = os.environ["ODIN_INTERNAL_AGENT_ADDRESS"]
    elif planet_id == PlanetID.HEIMDALL_INTERNAL:
        address = os.environ["HEIMDALL_INTERNAL_AGENT_ADDRESS"]
    else:
        raise ValueError(f"{planet_id!r} is not a value {PlanetID}")
    return format_addr(address)


def get_vault_avatar_address(planet_id: PlanetID) -> str:
    if planet_id == PlanetID.ODIN:
        address = os.environ["ODIN_AVATAR_ADDRESS"]
    elif planet_id == PlanetID.HEIMDALL:
        address = os.environ["HEIMDALL_AVATAR_ADDRESS"]
    elif planet_id == PlanetID.ODIN_INTERNAL:
        address = os.environ["ODIN_INTERNAL_AVATAR_ADDRESS"]
    elif planet_id == PlanetID.HEIMDALL_INTERNAL:
        address = os.environ["HEIMDALL_INTERNAL_AVATAR_ADDRESS"]
    else:
        raise ValueError(f"{planet_id!r} is not a value {PlanetID}")
    return format_addr(address)
