from dataclasses import dataclass
from typing import List, Union


@dataclass
class SQSMessageRecord:
    messageId: str
    receiptHandle: str
    body: object
    attributes: dict
    messageAttributes: dict
    md5OfBody: str
    eventSource: str
    eventSourceARN: str
    awsRegion: str


@dataclass
class SQSMessage:
    Records: Union[List[SQSMessageRecord], dict]

    def __post_init__(self):
        self.Records = [SQSMessageRecord(**x) for x in self.Records]


def handle(event, context):
    message = SQSMessage(**event)
    for record in message.Records:
        print(record.body)
