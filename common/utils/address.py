import hashlib

from common.utils.receipt import PlanetID


def format_addr(addr: str) -> str:
    """
    Check and reformat input address if not starts with `0x`.
    """
    if not addr.startswith("0x"):
        return f"0x{addr}"
    return addr


def derive_vault_address(planet_id: PlanetID) -> bytes:
    magic = b'plid'
    hasher = hashlib.sha256()
    hasher.update(magic)
    hasher.update(planet_id.value)
    return hasher.digest()[:20]
