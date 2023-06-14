from enum import Enum, IntEnum


class Currency(Enum):
    NCG = "NCG"
    CRYSTAL = "CRYSTAL"
    GARAGE = "GARAGE"


class Store(IntEnum):
    TEST = 0
    APPLE = 1
    GOOGLE = 2
    APPLE_TEST = 91
    GOOGLE_TEST = 92


class ReceiptStatus(IntEnum):
    INIT = 0
    VALIDATION_REQUEST = 1
    VALID = 10
    INVALID = 91
    UNKNOWN = 99


class TxStatus(IntEnum):
    CREATED = 1
    STAGED = 2
    SUCCESS = 10
    FAILURE = 91
    INVALID = 92
    NOT_FOUND = 93
    UNKNOWN = 99


class GarageActionType(IntEnum):
    LOAD = 1
    TRANSFER = 2
    UNLOAD = 3
