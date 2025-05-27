from pydantic import BaseModel as BaseSchema


class L10NSchema(BaseSchema):
    host: str
    category: str
    product: str
