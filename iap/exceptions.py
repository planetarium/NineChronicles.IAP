from typing import Union, Optional
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

