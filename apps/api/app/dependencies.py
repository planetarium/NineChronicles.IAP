from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import config

engine = create_engine(config.pg_dsn, echo=config.db_echo)


def session():
    # scoped_session 은 스레드 로컬이다. 동기 엔드포인트와 이 의존성의 정리 코드가 서로 다른
    # 스레드풀 스레드에서 돌면 close() 가 엉뚱한 세션을 닫고 실제 세션은 연결을 쥔 채
    # idle in transaction 으로 남아 풀(5+10)이 고갈된다. 요청 하나가 Session 하나를 직접 쥔다.
    with Session(engine) as sess:
        yield sess
