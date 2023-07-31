def format_addr(addr: str) -> str:
    """
    Check and reformat input address if not starts with `0x`.
    """
    if not addr.startswith("0x"):
        return f"0x{addr}"
    return addr
