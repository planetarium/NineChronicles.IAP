import json
from dataclasses import dataclass, fields
from typing import Union, List


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

    # Avoid TypeError when init dataclass. https://stackoverflow.com/questions/54678337/how-does-one-ignore-extra-arguments-passed-to-a-dataclass # noqa
    def __init__(self, **kwargs):
        names = set([f.name for f in fields(self)])
        for k, v in kwargs.items():
            if k in names:
                if k == 'body' and isinstance(v, str):
                    v = json.loads(v)
                setattr(self, k, v)


@dataclass
class SQSMessage:
    Records: Union[List[SQSMessageRecord], dict]

    def __post_init__(self):
        self.Records = [SQSMessageRecord(**x) for x in self.Records]
