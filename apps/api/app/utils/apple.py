from typing import List

import jwt
import requests
from fastapi import HTTPException

from shared.utils.apple import get_jwt


def get_tx_ids(
    order_id: str, credential: str, bundle_id: str, key_id: str, issuer_id: str
) -> List[str]:
    resp = requests.get(
        f"https://api.storekit.itunes.apple.com/inApps/v1/lookup/{order_id}",
        headers={
            "Authorization": f"Bearer {get_jwt(credential, bundle_id, key_id, issuer_id)}"
        },
    )

    result = resp.json()
    tx_ids = []
    if not result["status"] == 0:
        raise HTTPException(
            status_code=400, detail=f"Apple API error: {result['status']}"
        )
    if len(result["signedTransactions"]) < 1:
        raise HTTPException(
            status_code=400, detail=f"Apple API error: {result['signedTransactions']}"
        )
    for signed in result["signedTransactions"]:
        decoded = jwt.decode(
            signed, algorithms=["ES256"], options={"verify_signature": False}
        )
        transaction_id = decoded["transactionId"]
        tx_ids.append(transaction_id)
    return tx_ids
