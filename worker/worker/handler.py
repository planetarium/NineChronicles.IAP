import json
import logging
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple, Union

import boto3
from botocore.exceptions import ClientError

from _crypto import Account
from _graphql import GQL


@dataclass
class SQSMessageRecord:
    messageId: str
    receiptHandle: str
    body: Union[dict, str]
    attributes: dict
    messageAttributes: dict
    md5OfBody: str
    eventSource: str
    eventSourceARN: str
    awsRegion: str

    def __post_init__(self):
        self.body = json.loads(self.body) if type(self.body) == str else self.body


@dataclass
class SQSMessage:
    Records: Union[List[SQSMessageRecord], dict]

    def __post_init__(self):
        self.Records = [SQSMessageRecord(**x) for x in self.Records]


def process(message: SQSMessageRecord) -> Tuple[bool, str, Optional[str]]:
    stage = os.environ.get("STAGE", "development")
    region = os.environ.get("REGION", "us-east-2")
    logging.debug(f"STAGE: {stage} || REGION: {region}")
    client = boto3.client("ssm", region_name=region)
    try:
        kms_key_id = client.get_parameter(Name=f"{stage}_9c_IAP_KMS_KEY_ID", WithDecryption=True)
    except ClientError as e:
        logging.error(e)
        return False, str(e), None

    account = Account(kms_key_id["Parameter"]["Value"])
    gql = GQL()
    nonce = gql.get_next_nonce(account.address)
    unsigned_tx = gql.create_action(
        "transfer_asset", pubkey=account.pubkey, nonce=nonce,
        sender=account.address, recipient=message.body.get("recipient"),
        currency=message.body.get("currency"), amount=message.body.get("amount"),
        memo="Action from IAP Worker",
    )
    signature = account.sign_tx(unsigned_tx)
    signed_tx = gql.sign(unsigned_tx, signature)
    return gql.stage(signed_tx)


def handle(event, context):
    message = SQSMessage(Records=event.get("Records", {}))
    logging.debug("=== Message from SQS ====\n")
    logging.debug(message)
    logging.debug("=== Message end ====\n")
    for i, record in enumerate(message.Records):
        # Always 1 record in message since IAP sends one record at a time.
        # TODO: Handle exceptions and send messages to DLQ
        success, msg, tx_id = process(record)
        logging.info(
            f"{i + 1}/{len(message.Records)} : {'Success' if success else 'Fail'} with message: "
            f"\n\t{msg}"
            f"\n\tTx. ID: {tx_id}"
        )
