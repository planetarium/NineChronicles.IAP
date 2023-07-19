from pydantic import BaseModel as Schema


class ItemSchema(Schema):
    id: int
    name: str

    class Config:
        orm_mode = True
