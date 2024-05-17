import time
import urllib.parse
from typing import Tuple, Optional

import jwt
import requests

from common import logger
from common.utils.apple import get_jwt
from iap import settings
from iap.schemas.receipt import ApplePurchaseSchema


def validate_apple(package_name: str, tx_id: str) -> Tuple[bool, str, Optional[ApplePurchaseSchema]]:
    headers = {
        "Authorization": f"Bearer {get_jwt(settings.APPLE_CREDENTIAL, package_name, settings.APPLE_KEY_ID, settings.APPLE_ISSUER_ID)}"
    }
    encoded_tx_id = urllib.parse.quote_plus(tx_id)
    resp = requests.get(settings.APPLE_VALIDATION_URL.format(transactionId=encoded_tx_id), headers=headers)
    if resp.status_code != 200:
        time.sleep(1)
        resp = requests.get(settings.APPLE_VALIDATION_URL.format(transactionId=encoded_tx_id), headers=headers)
        if resp.status_code != 200:
            return False, f"Purchase state of this receipt is not valid: {resp.text}", None
    try:
        data = jwt.decode(resp.json()["signedTransactionInfo"], options={"verify_signature": False})
        logger.debug(data)
        schema = ApplePurchaseSchema(**data)
    except:
        return False, f"Malformed apple transaction data for {encoded_tx_id}", None
    else:
        return True, "", schema
