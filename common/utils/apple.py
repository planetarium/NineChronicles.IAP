from time import time

import jwt


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
