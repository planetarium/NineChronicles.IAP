import time
import urllib.parse
from typing import Tuple, Optional

import jwt
import requests

from shared.schemas.receipt import ApplePurchaseSchema


def validate_apple(
    token: str, apple_validation_url: str, tx_id: str
) -> Tuple[bool, str, Optional[ApplePurchaseSchema]]:
    headers = {"Authorization": f"Bearer {token}"}
    encoded_tx_id = urllib.parse.quote_plus(tx_id)
    resp = requests.get(
        apple_validation_url.format(transactionId=encoded_tx_id), headers=headers
    )
    if resp.status_code != 200:
        time.sleep(1)
        resp = requests.get(
            apple_validation_url.format(transactionId=encoded_tx_id), headers=headers
        )
        if resp.status_code != 200:
            return (
                False,
                f"Purchase state of this receipt is not valid: {resp.text}",
                None,
            )
    try:
        data = jwt.decode(
            resp.json()["signedTransactionInfo"], options={"verify_signature": False}
        )
        schema = ApplePurchaseSchema(**data)
    except:
        return False, f"Malformed apple transaction data for {encoded_tx_id}", None
    else:
        return True, "", schema
