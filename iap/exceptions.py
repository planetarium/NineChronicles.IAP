from typing import Union
from uuid import uuid4


class ReceiptNotFoundException(Exception):
    def __init__(self, receipt_uuid: Union[str, uuid4]):
        super().__init__()
        self.receipt_uuid = receipt_uuid

    def __str__(self):
        return f"Receipt {self.receipt_uuid} not found."
