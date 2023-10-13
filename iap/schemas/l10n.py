from typing import List

from pydantic import BaseModel as BaseSchema


class L10NSchema(BaseSchema):
    host: str
    category: str
    product: str


class CsvSchema(BaseSchema):
    header: List[str]
    body: List[List[str]]
