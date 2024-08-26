from __future__ import annotations

import hashlib
import hmac

import eth_utils


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

    def derive(self, key: str) -> Address:
        return Address(
            self.__checksum_encode(hmac.new(
                key.encode("utf-8"),
                self.raw,
                digestmod=hashlib.sha1
            ).digest())
        )

    def __checksum_encode(self, addr: bytes) -> str:  # Takes a 20-byte binary address as input
        """
        Convert input address to checksum encoded address without prefix "0x"
        See [ERC-55](https://eips.ethereum.org/EIPS/eip-55)

        :param addr: 20-bytes binary address
        :return: checksum encoded address as string
        """
        hex_addr = addr.hex()
        checksum_buffer = ""

        # Treat the hex address as ascii/utf-8 for keccak256 hashing
        hashed_address = eth_utils.keccak(text=hex_addr).hex()

        # Iterate over each character in the hex address
        for nibble_index, character in enumerate(hex_addr):
            if character in "0123456789":
                # We can't upper-case the decimal digits
                checksum_buffer += character
            elif character in "abcdef":
                # Check if the corresponding hex digit (nibble) in the hash is 8 or higher
                hashed_address_nibble = int(hashed_address[nibble_index], 16)
                if hashed_address_nibble > 7:
                    checksum_buffer += character.upper()
                else:
                    checksum_buffer += character
            else:
                raise eth_utils.ValidationError(
                    f"Unrecognized hex character {character!r} at position {nibble_index}"
                )
        return checksum_buffer

    def __eq__(self, other: Address):
        return self.raw == other.raw
