from enum import Enum, IntEnum


# WARNING: Please match all maps with iap/frontend/src/const.js
#  Mismatch can lead frontend error


class PackageName(Enum):
    """
    # PackageName
    ---
    """
    NINE_CHRONICLES_M = "com.planetariumlabs.ninechroniclesmobile"
    NINE_CHRONICLES_K = "com.planetariumlabs.ninechroniclesmobilek"


class Currency(Enum):
    """
    # Currency
    ---
    Currencies that are used inside Nine Chronicles.

    - **`NCG`**

        NCG is 9c's main in-game token.

    - **`CRYSTAL`**

        CRYSTAL is token that is used to combine items.

    - **`GARAGE`**

        `GARAGE` is token that is used to load fungible assets/fungible items into garage from balance/inventory.
    """
    NCG = "NCG"
    CRYSTAL = "CRYSTAL"
    GARAGE = "GARAGE"


class Store(IntEnum):
    """
    # Store type
    ---

    - **0: `TEST`**

        This is store type to test. This store only works on debug mode.  
        When you request receipt validation with this type of store, validation process will be skipped.

    - **1: `APPLE` (Appstore)**

        This is `production` apple appstore.  
        This type of store cannot verify receipt created from sandbox appstore.

    - **2: `GOOGLE` (Play store)**

        This is `production` google play store.  
        This type of store cannot verify receipt created from sandbox play store.

    - **91: `APPLE_TEST` (Sandbox appstore)**

        This is `sandbox` apple appstore.  
        This type of store cannot verify receipt created from production appstore.

    - **92: `GOOGLE_TEST` (Sandbox play store)**

        This is `sandbox` google play store.  
        This type of store cannot verify receipt created from production play store.
    """
    TEST = 0
    APPLE = 1
    GOOGLE = 2
    APPLE_TEST = 91
    GOOGLE_TEST = 92


class ProductType(Enum):
    """
    # ProductType
    ---
    Product type is the flag to specify IAP product type.

    - **`SINGLE`**

        `SINGLE` type product has just one fungible item.  
        `SINGLE` type product has no limitation to buy.

    - **`PACKAGE`**

        `PACKAGE` type product has multiple fungible items in it.  
        `PACKAGE` type product has daily/weekly limitation to buy.  
        If all limitation is exhausted, the package will be locked before next period.
    """
    SINGLE = "SINGLE"
    PKG = "PACKAGE"


class ReceiptStatus(IntEnum):
    """
    Receipt Status
    ---
    This enum represents current validation status of receipt.

    - **0: `INIT`**

        First state of receipt. When the validation request comes, data is saved with this status.

    - **1: `VALIDATION_REQUEST`**

        The IAP service requests receipt validation to google/apple and waiting for response.  
        If receipt status stuck on this status, that means no response received from google/apple.

    - **10: `VALID`**

        Receipt validation succeed.  
        The IAP service send message to create transaction. Please check transaction status to check.

    - **20: `REFUNDED_BY_ADMIN`**

        Receipt has been refunded by administrator.  
        This occurs due to lack of garage stock or server-side failure.  
        This status does not make any penalty to buyer.

    - **91: `INVALID`**

        Receipt validation failed.  
        The IAP service will return exception and no transaction will be created.

    - **92: `REFUNDED_BY_BUYER`**

        Receipt has been refunded by buyer.  
        If a receipt is refunded by buyer, it can cause halting Mead.

    - **93: `PURCHASE_LIMIT_EXCEED`**

        Purchase limit reached for the daily/weekly limit existing product.

    - **94: `TIME_LIMIT`**

        Purchase timestamp is not between target product's open/close timestamp.
        This purchase is executed in appstore, so admin should refund this purchase in manual.

    - **95: `REQUIRED_LEVEL`**

        Does not met required level to get this product.

    - **99: `UNKNOWN`**

        An unhandled error case. This is reserve to catch all other errors.  
        If you see this status, please contact with administrator.

    """
    INIT = 0
    VALIDATION_REQUEST = 1
    VALID = 10
    REFUNDED_BY_ADMIN = 20
    INVALID = 91
    REFUNDED_BY_BUYER = 92
    PURCHASE_LIMIT_EXCEED = 93
    TIME_LIMIT = 94
    REQUIRED_LEVEL = 95
    UNKNOWN = 99


class TxStatus(IntEnum):
    """
    # Transaction Status
    ---
    Transaction status from IAP service to buyer to send purchased items.

    - **1: `CREATED`**

        The transaction is created, successfully signed and ready to stage.

    - **2: `STAGED`**

        The transaction is successfully stated into the chain.

    - **10: `SUCCESS`**

        The transaction is successfully added to block.

    - **91: `FAILURE`**

        The transaction is failed.

    - **92: `INVALID`**

        The transaction is invalid.  
        If you see this status, please contact to administrator.

    - **93: `NOT_FOUND`**

        The transaction is not found in chain.

    - **94: `FAIL_TO_CREATE`**

        Transaction creation is failed.  
        If you see this status, please contact to administrator.

    - **99: `UNKNOWN`**

        An unhandled error case. This is reserve to catch all other errors.  
        If you see this status, please contact with administrator.

    """
    CREATED = 1
    STAGED = 2
    SUCCESS = 10
    FAILURE = 91
    INVALID = 92
    NOT_FOUND = 93
    FAIL_TO_CREATE = 94
    UNKNOWN = 99


class GarageActionType(IntEnum):
    """
    # Garage action type
    ---

    - **1: `LOAD`**

        Represents `LoadIntoMyGarages` action.

    - **2: `DELIVER`**

        Represents `DeliverToOthersGarages` action.

    - **3: `UNLOAD`**

        Represents `UnloadFromMyGarages` action.

    """
    LOAD = 1
    DELIVER = 2
    UNLOAD = 3


# GOOGLE
class GooglePurchaseState(IntEnum):
    PURCHASED = 0
    CANCELED = 1
    PENDING = 2


class GoogleConsumptionState(IntEnum):
    YET_BE_CONSUMED = 0
    CONSUMED = 1


class GooglePurchaseType(IntEnum):
    TEST = 0  # Purchase from license testing account
    PROMO = 1  # Purchase using promo code
    REWARDED = 2  # Watching video instead of paying


class GoogleAckState(IntEnum):
    YET_BE_ACKNOWLEDGED = 0
    ACKNOWLEDGED = 1


class ProductAssetUISize(Enum):
    """
    # ProductAssetUISize

    Size of product in client UI.
    Format of {width}x{height}.

    - **1x1**: Width 1 * Height 1
    - **1x2**: Width 1 * Height 2
    - **1x3**: Width 1 * Height 3
    - **1x4**: Width 1 * Height 4
    - **2x1**: Width 2 * Height 1
    - **2x2**: Width 2 * Height 2
    - **2x3**: Width 2 * Height 3
    - **2x4**: Width 2 * Height 4
    - **3x1**: Width 3 * Height 1
    - **3x2**: Width 3 * Height 2
    - **3x3**: Width 3 * Height 3
    - **3x4**: Width 3 * Height 4
    - **4x1**: Width 4 * Height 1
    - **4x2**: Width 4 * Height 2
    - **4x3**: Width 4 * Height 3
    - **4x4**: Width 4 * Height 4
    """
    ONE_BY_ONE = "1x1"
    ONE_BY_TWO = "1x2"
    ONE_BY_THREE = "1x3"
    ONE_BY_FOUR = "1x4"
    TWO_BY_ONE = "2x1"
    TWO_BY_TWO = "2x2"
    TWO_BY_THREE = "2x3"
    TWO_BY_FOUR = "2x4"
    THREE_BY_ONE = "3x1"
    THREE_BY_TWO = "3x2"
    THREE_BY_THREE = "3x3"
    THREE_BY_FOUR = "3x4"
    FOUR_BY_ONE = "4x1"
    FOUR_BY_TWO = "4x2"
    FOUR_BY_THREE = "4x3"
    FOUR_BY_FOUR = "4x4"


class ProductRarity(Enum):
    """
    # ProductRarity

    Rarity of this product.
    Rarity is used to show bg color in client.
    You can find this in Lib9c ([Lib9c/Model/EnumType/Grade.cs](https://github.com/planetarium/lib9c/blob/main/Lib9c/Model/EnumType/Grade.cs))

    - **Normal**: Normal. BG color: gray
    - **Rare**: Rare. BG color: green
    - **Epic**: Epic. BG color: blue
    - **Unique**: Unique. BG color: yellow
    - **Legendary**: Legendary. BG color: purple
    """
    NORMAL = "Normal"
    RARE = "Rare"
    EPIC = "Epic"
    UNIQUE = "Unique"
    LEGENDARY = "Legendary"
