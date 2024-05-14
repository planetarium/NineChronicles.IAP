from typing import Optional
from uuid import uuid1

import bencodex


class ActionBase:
    def __init__(self, type_id: str, _id: Optional[str] = None, **kwargs):
        self._id = _id if _id else uuid1().hex
        self._type_id = type_id

    @property
    def plain_value(self):
        return {
            "type_id": self._type_id,
            "values": self._plain_value
        }

    @property
    def _plain_value(self):
        raise NotImplementedError

    @property
    def serialized_plain_value(self):
        return bencodex.dumps(self.plain_value)
