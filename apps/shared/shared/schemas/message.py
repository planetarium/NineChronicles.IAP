from pydantic import BaseModel


class SendProductMessage(BaseModel):
    uuid: str
