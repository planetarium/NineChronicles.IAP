from __future__ import annotations


class Address:
    def __init__(self, addr: str):
        if addr.startswith("0x"):
            if len(addr) != 42:
                raise ValueError("Address with 0x prefix must have exact 42 chars.")
            self.raw = bytes.fromhex(addr[2:])
        else:
            if len(addr) != 40:
                raise ValueError("Address without 0x prefix must have exact 40 chars.")
            self.raw = bytes.fromhex(addr)

    @property
    def long_format(self):
        return f"0x{self.raw.hex()}"

    @property
    def short_format(self):
        return self.raw.hex()

    def __eq__(self, other: Address):
        return self.raw == other.raw
