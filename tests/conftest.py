import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session


@pytest.fixture
def session():
    DB_URI = ""
    engine = create_engine(DB_URI)
    sess = scoped_session(sessionmaker(bind=engine))
    try:
        yield sess
    finally:
        sess.rollback()
        sess.close()
