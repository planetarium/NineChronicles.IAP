from uuid import uuid1


class ActionBase:
    def __init__(self, type_id: str, **kwargs):
        self._id = uuid1().hex
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
