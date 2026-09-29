from pydantic import BaseModel


class SendProductMessage(BaseModel):
    uuid: str


class SendGrantMessage(BaseModel):
    """
    (PLD-1564) 영수증 없는 지급 트리거. 아웃박스 멱등키만 보낸다.

    페이로드에 지급 내용(상품·수량·주소)을 담지 않는 이유는 `SendProductMessage` 와 같다 —
    권위 있는 값은 DB 행(`grant_outbox`)이고, 메시지가 중복/재전송돼도 행이 한 번만 처리되게 하려면
    워커가 DB 를 다시 읽어야 한다.
    """

    external_ref: str
