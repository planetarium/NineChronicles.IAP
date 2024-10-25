# This worker manually issues token from input data which in following format:
#  List[Tuple[{ticker:str}, {decimal_places:int}, {fungible_id:str}, {item_id:int}, {amount:int}]]
#  Use `ticker`, `decimal_places` and `amount` for FAV
#    minters of the FAV is always assumed as None.
#  Use `fungible_id` or `item_id` and `amount` for item.
#    If both fungible_id and item_id are provided, the worker uses fungible_id.
import datetime
import os
from decimal import Decimal

from common import logger
from common._crypto import Account
from common._graphql import GQL
from common.consts import ITEM_FUNGIBLE_ID_DICT
from common.lib9c.actions.issue_tokens_from_garage import FavIssueSpec, ItemIssueSpec, IssueTokensFromGarage
from common.lib9c.models.fungible_asset_value import FungibleAssetValue
from common.utils.aws import fetch_parameter, fetch_kms_key_id
from common.utils.receipt import PlanetID
from common.utils.transaction import create_unsigned_tx, append_signature_to_unsigned_tx

# NOTE: Use this lambda function by executing manually in AWS console.

# Set these values by manual form here
NONCE = 0
PLANET_ID = PlanetID.XXX
GQL_URL = "https://example.com/graphql"  # Use Odin/Heimdall GQL host
USE_ADHOC = True
# to here

HEADLESS_GQL_JWT_SECRET = fetch_parameter(
    os.environ.get("REGION_NAME"),
    f"{os.environ.get('STAGE')}_9c_IAP_HEADLESS_GQL_JWT_SECRET",
    True
)["Value"]
DICT_HEADER = ("ticker", "decimal_places", "fungible_id", "item_id", "amount")


def issue(event, context):
    spec_list = []
    gql = GQL(GQL_URL, HEADLESS_GQL_JWT_SECRET)
    account = Account(fetch_kms_key_id(os.environ.get("STAGE"), os.environ.get("REGION_NAME"), adhoc=USE_ADHOC))

    for data in event:
        data = dict(zip(DICT_HEADER, data))
        if data["ticker"]:
            spec_list.append(FavIssueSpec(FungibleAssetValue.from_raw_data(
                ticker=data["ticker"], decimal_places=int(data["decimal_places"]), minters=None,
                amount=Decimal(data["amount"]))
            ))
        else:
            fungible_id = data["fungible_id"] if data["fungible_id"] else ITEM_FUNGIBLE_ID_DICT[data["item_id"]]
            spec_list.append(ItemIssueSpec(fungible_item_id=fungible_id, amount=int(data["amount"])))

    action = IssueTokensFromGarage(values=spec_list)
    utx = create_unsigned_tx(
        planet_id=PLANET_ID, public_key=account.pubkey.hex(), address=account.address, nonce=NONCE,
        plain_value=action.plain_value, timestamp=datetime.datetime.utcnow() + datetime.timedelta(days=1)
    )
    signature = account.sign_tx(utx)
    signed_tx = append_signature_to_unsigned_tx(utx, signature)
    success, message, tx_id = gql.stage(signed_tx)

    logger.info(f"{success}::'{message}'::{tx_id} with nonce {NONCE}")
    logger.debug(signed_tx.hex())
    return success, message, tx_id, NONCE, signed_tx.hex()
