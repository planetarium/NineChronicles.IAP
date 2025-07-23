import pytest

from shared.lib9c.models.address import Address


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


@pytest.mark.parametrize("addr",
                         [
                             "0xa5f7e0bd63AD2749D66380f36Eb33Fe0ba50A27X",  # Invalid character
                             "a5f7e0bd63AD2749D66380f36Eb33Fe0ba50A27X",  # Invalid character
                             "0xa5f7e0bd63AD2749D66380f36Eb33Fe0ba50A2",  # Length
                             "a5f7e0bd63AD2749D66380f36Eb33Fe0ba50A2",  # Length
                         ])
def test_address_error(addr):
    with pytest.raises(ValueError) as e:
        Address(addr)


@pytest.mark.parametrize(("key", "result"), [
    ("key1", "0x518c0044a81c7d3747Ad416Df7227e53233F2e10"),
    ("key2", "0xEb5cC07Eb104B082C1ae82E018340e989700ca31")
])
def test_address_derive(key, result):
    addr = Address("0xa5f7e0bd63AD2749D66380f36Eb33Fe0ba50A27D")
    assert addr.derive(key) == Address(result)
