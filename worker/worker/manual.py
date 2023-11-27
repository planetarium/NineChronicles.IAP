import datetime
import os
import uuid

from common._crypto import Account
from common._graphql import GQL
from common.utils.actions import create_unload_my_garages_action_plain_value
from common.utils.aws import fetch_kms_key_id
from common.utils.receipt import PlanetID
from common.utils.transaction import append_signature_to_unsigned_tx, create_unsigned_tx

stage = os.environ.get("STAGE", "development")
region_name = os.environ.get("REGION_NAME", "us-east-2")


def handle(event, context):
    if not os.path.exists("unload_data.json"):
        print("=== Instruction ===")
        print("Duplicate `unload_data.json.example` to `unload_data.json`.")
        print("Edit `unload_data.json` to real values to unload.")
        print("Run this function.")
        print("!!! Delete your `unload_data.json` to avoid accident !!!")
        return

    account = Account(fetch_kms_key_id(stage, region_name))
    gql = GQL()
    with open("unload_data.json", "r") as f:
        unload_data = f.read()

    nonce = gql.get_next_nonce(account.address)

    print(f"{len(unload_data)} requests to unload.")
    for i, unload in enumerate(unload_data):
        print(f"{i + 1} / {len(unload_data)} : Unload to {unload['avatar_addr']}")
        try:
            unload_from_garage = create_unload_my_garages_action_plain_value(
                id=uuid.uuid1().hex,
                fav_data=unload["fav_data"],
                avatar_addr=unload["avatar_addr"],
                item_data=unload["item_data"],
                memo=unload["memo"]
            )
            utx = create_unsigned_tx(
                planet_id=PlanetID.ODIN,
                public_key=account.pubkey.hex(),
                address=account.address,
                nonce=nonce,
                plain_value=unload_from_garage,
                timestamp=datetime.datetime.utcnow() + datetime.timedelta(days=1)
            )
            signature = account.sign_tx(utx)
            signed_tx = append_signature_to_unsigned_tx(utx, signature)
            success, msg, tx_id = gql.stage(signed_tx)
            print(f"Unload {'Success' if success else 'Failure'} :: {msg}")
            if tx_id:
                print(f"Tx. ID: {tx_id}")
            if success:
                nonce += 1
        except Exception as e:
            print(f"An Error occurred: {e}. Skip this request and continue to next...")
            continue

    print("All unloads are finished.")
    print("!!! Do not forget to delete your `unload_data.json` to avoid accident!!!")
