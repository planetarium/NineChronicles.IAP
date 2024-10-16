# NOTE: Use this lambda function by executing manually in AWS console.
import datetime
import os

from common import logger
from common._crypto import Account
from common._graphql import GQL
from common.lib9c.actions.transfer_assets import TransferAssets
from common.lib9c.models.address import Address
from common.lib9c.models.fungible_asset_value import FungibleAssetValue
from common.utils.aws import fetch_parameter, fetch_kms_key_id
from common.utils.receipt import PlanetID
from common.utils.transaction import create_unsigned_tx, append_signature_to_unsigned_tx

# Set these values by manual form here
PLANET_ID = PlanetID.XXX
GQL_URL = "https://example.com/graphql"  # Use Odin/Heimdall GQL host
USE_ADHOC = True
# to here

HEADLESS_GQL_JWT_SECRET = fetch_parameter(
    os.environ.get("REGION_NAME"),
    f"{os.environ.get('STAGE')}_9c_IAP_HEADLESS_GQL_JWT_SECRET",
    True
)["Value"]
DICT_HEADER = ("nonce", "sender", "recipients", "memo")

"""
--- Valid sample for event data ---
[
  3, "0xDbF4c6d0D7C74D390fADae680f2144D885c878df",
  [
    ["0x49D5FcEB955800B2c532D6319E803c7D80f817Af", "FAV__CRYSTAL", 18, 1000],
    ["0xcfcd6565287314ff70e4c4cf309db701c43ea5bd", "FAV__RUNE_GOLDENLEAF", 0, 10]
  ]
]
"""


def transfer(event, context):
    gql = GQL(GQL_URL, HEADLESS_GQL_JWT_SECRET)
    account = Account(fetch_kms_key_id(os.environ.get("STAGE"), os.environ.get("REGION_NAME"), adhoc=USE_ADHOC))

    nonce = event[0]
    sender = Address(event[1])
    recipients = []
    for r_data in event[2]:
        recipients.append((
            Address(r_data[0]),
            FungibleAssetValue.from_raw_data(
                ticker=r_data[1], decimal_places=r_data[2], minters=None, amount=r_data[3]
            )
        ))

    action = TransferAssets(sender=sender, recipients=recipients, memo="Manual send from IAP ad-hoc")
    utx = create_unsigned_tx(
        planet_id=PLANET_ID, public_key=account.pubkey.hex(), address=account.address, nonce=nonce,
        plain_value=action.plain_value, timestamp=datetime.datetime.utcnow() + datetime.timedelta(days=1)
    )
    signature = account.sign_tx(utx)
    signed_tx = append_signature_to_unsigned_tx(utx, signature)
    success, message, tx_id = gql.stage(signed_tx)

    logger.info(f"{success}::'{message}'::{tx_id} with nonce {nonce}")
    logger.debug(signed_tx.hex())
    return success, message, tx_id, nonce, signed_tx.hex()
