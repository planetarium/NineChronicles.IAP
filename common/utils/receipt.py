from enum import Enum


class PlanetID(bytes, Enum):
    ODIN = b'0x000000000000'
    HEIMDALL = b'0x000000000001'
    ODIN_INTERNAL = b'0x100000000000'
    HEIMDALL_INTERNAL = b'0x100000000001'
