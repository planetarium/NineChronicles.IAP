# NOTE: Use this lambda function by executing manually in AWS console.
import os
from datetime import timedelta, datetime

from common import logger
from common._crypto import Account
from common._graphql import GQL
from common.lib9c.actions.issue_token import IssueToken, ItemSpec
from common.lib9c.models.fungible_asset_value import FungibleAssetValue
from common.utils.aws import fetch_parameter, fetch_kms_key_id
from common.utils.receipt import PlanetID
from common.utils.transaction import create_unsigned_tx, append_signature_to_unsigned_tx

# NOTE: Set these values by manual from here
PLANET_ID = PlanetID.XXX
GQL_URL = "https://example.com/graphql"  # Use GQL host of desired chain
USE_ADHOC = True
#  to here

HEADLESS_GQL_JWT_SECRET = fetch_parameter(
    os.environ.get("REGION_NAME"),
    f"{os.environ.get('STAGE')}_9c_IAP_HEADLESS_GQL_JWT_SECRET",
    True
)["Value"]

DICT_HEADER = ["nonce", "avatar_addr", "fav_list", "item_list"]
"""
--- Valid sample of event data
[
    3, 
    "0xDbF4c6d0D7C74D390fADae680f2144D885c878df",
    [
        ["SOULSTONE_1001", 0, 100],
        ["CRYSTAL", 18, 100]
    ],
    [
        [500000, 100, false],
        [600201, 100, true]
    ]
]
"""


def issue_token(event, context):
    gql = GQL(GQL_URL, HEADLESS_GQL_JWT_SECRET)
    account = Account(fetch_kms_key_id(os.environ.get("STAGE"), os.environ.get("REGION_NAME"), adhoc=USE_ADHOC))
    data = dict(zip(DICT_HEADER, event))

    nonce = data["nonce"]
    fav_list = []
    for fav in data["fav_list"]:
        fav_list.append(FungibleAssetValue.from_raw_data(ticker=fav[0], decimal_places=fav[1], amount=fav[2]))
    item_list = []
    for item in data["item_list"]:
        item_list.append(ItemSpec(item_id=item[0], amount=item[1], tradable=item[2]))
    action = IssueToken(avatar_addr=data["avatar_addr"], fav_list=fav_list, item_list=item_list)
    utx = create_unsigned_tx(planet_id=PLANET_ID, public_key=account.pubkey.hex(), address=account.address, nonce=nonce,
                             plain_value=action.plain_value, timestamp=datetime.utcnow() + timedelta(days=1)
                             )
    signature = account.sign_tx(utx)
    signed_tx = append_signature_to_unsigned_tx(utx, signature)
    success, message, tx_id = gql.stage(signed_tx)

    logger.info(f"{success}::'{message}'::{tx_id} with nonce {nonce}")
    logger.debug(signed_tx.hex())
    return success, message, tx_id, nonce, signed_tx.hex()
