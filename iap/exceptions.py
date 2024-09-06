from typing import Union, Optional, List
from uuid import uuid4


class ReceiptNotFoundException(Exception):
    def __init__(self, receipt_uuid: Union[str, uuid4], order_id: Optional[str]):
        super().__init__()
        self.receipt_uuid = receipt_uuid
        self.order_id = order_id

    def __str__(self):
        if self.receipt_uuid:
            return f"Receipt {self.receipt_uuid} not found."
        elif self.order_id:
            return f"Receipt {self.order_id} not found."


class InsufficientUserDataException(Exception):
    def __init__(self, receipt_uuid: Union[str, uuid4], order_id: Optional[str], empty_data: List[str]):
        super().__init__()
        self.receipt_uuid = receipt_uuid
        self.order_id = order_id
        self.empty_data = empty_data

    def __str__(self):
        return f"Receipt {self.receipt_uuid} :: {self.order_id} has insufficient user data: {self.empty_data}"
