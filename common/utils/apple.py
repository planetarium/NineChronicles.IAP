from time import time

import jwt

from settings import APPLE_CREDENTIAL, APPLE_BUNDLE_ID, APPLE_KEY_ID, APPLE_ISSUER_ID


def get_jwt() -> str:
    header = {
        "alg": "ES256",
        "kid": APPLE_KEY_ID,
        "typ": "JWT"
    }
    data = {
        "iss": APPLE_ISSUER_ID,
        "iat": int(float(time())),
        "exp": int(float(time())) + 60,  # Exp after 60 seconds
        "aud": "appstoreconnect-v1",  # Fixed
        "bid": APPLE_BUNDLE_ID
    }
    return jwt.encode(data, APPLE_CREDENTIAL, algorithm="ES256", headers=header)
