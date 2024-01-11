import pytest

from common.lib9c.models.address import Address


@pytest.mark.parametrize("addr",
                         ["0xa5f7e0bd63AD2749D66380f36Eb33Fe0ba50A27D",
                          "0xb3cbca0e64aeb4b5b861047fe1db5a1bec1c241f",
                          "a5f7e0bd63AD2749D66380f36Eb33Fe0ba50A27D",
                          "b3cbca0e64aeb4b5b861047fe1db5a1bec1c241f",
                          ])
def test_address(addr):
    address = Address(addr)
    assert len(address.raw) == 20
    if addr.startswith("0x"):
        assert address.raw == bytes.fromhex(addr[2:])
        assert address.long_format == addr.lower()
    else:
        assert address.raw == bytes.fromhex(addr)
        assert address.short_format == addr.lower()
