from base64 import b64decode
from datetime import datetime
from typing import Dict, Union

from pydantic import BaseModel as BaseSchema, validator


class GoogleNotificationMessageSchema(BaseSchema):
    attributes: Dict[str, str]
    data: str
    messageId: str
    message_id: str
    publishTime: Union[datetime, str]
    publish_time: Union[datetime, str]

    @validator("publishTime")
    @validator("publish_time")
    def convert_datetime(cls, data):
        return datetime.fromisoformat(data)

    @validator("data")
    def decode_data(cls, data):
        return b64decode(data)


class GoogleNotificationSchema(BaseSchema):
    message: GoogleNotificationMessageSchema
    subscription: str
