from time import time
from typing import List

from fastapi import HTTPException
import jwt
import requests


def get_jwt(credential: str, bundle_id: str, key_id: str, issuer_id: str) -> str:
    header = {
        "alg": "ES256",
        "kid": key_id,
        "typ": "JWT"
    }
    data = {
        "iss": issuer_id,
        "iat": int(float(time())),
        "exp": int(float(time())) + 60,  # Exp after 60 seconds
        "aud": "appstoreconnect-v1",  # Fixed
        "bid": bundle_id
    }
    return jwt.encode(data, credential, algorithm="ES256", headers=header)


def get_tx_ids(order_id: str, credential: str, bundle_id: str, key_id: str, issuer_id: str) -> List[str]:
    resp = requests.get(
        f"https://api.storekit.itunes.apple.com/inApps/v1/lookup/{order_id}",
        headers={
            "Authorization": f"Bearer {get_jwt(credential, bundle_id, key_id, issuer_id)}"
        }
    )

    result = resp.json()
    tx_ids = []
    if not result["status"] == 0:
        raise HTTPException(status_code=400, detail=f"Apple API error: {result['status']}")
    if len(result["signedTransactions"]) < 1:
        raise HTTPException(status_code=400, detail=f"Apple API error: {result['signedTransactions']}")
    for signed in result["signedTransactions"]:
        decoded = jwt.decode(signed, algorithms=["ES256"], options={"verify_signature": False})
        transaction_id = decoded["transactionId"]
        tx_ids.append(transaction_id)
    return tx_ids


if __name__ == "__main__":
    apple_credential = """-----BEGIN PRIVATE KEY-----
MIGTAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBHkwdwIBAQQgKtMUPiiYWQh6ADr8
etfJtPqV8Fa1qHbDGYoYdnCmHNygCgYIKoZIzj0DAQehRANCAATq3zku/3f3+Fos
rp+hPWvuOYTP/NIGL3aFvaJITq8/whflRf0ggKLnp6sVd2lEhZkNFWEdb3f9mbT+
xHptTzqZ
-----END PRIVATE KEY-----
    """
    apple_bundle_id = "com.planetariumlabs.ninechroniclesmobile"
    apple_key_id = "X6LLA9R65S"
    apple_issuer_id = "b9ed8a81-782d-4720-a6ab-f921ad3a8510"
    get_tx_id("MSHMGJJZFW", apple_credential, apple_bundle_id, apple_key_id, apple_issuer_id)
