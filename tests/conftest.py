import os

import alembic
import pytest
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session


@pytest.fixture(scope="session", autouse=True)
def setup_alembic():
    config = Config("common/alembic.ini")
    config.set_main_option("script_location", "common/alembic")
    config.set_main_option("sqlalchemy.url", os.environ.get('DB_URI'))
    try:
        alembic.command.upgrade(config, "head")
        yield
    finally:
        alembic.command.downgrade(config, "base")


@pytest.fixture(scope="function")
def session(setup_alembic):
    engine = create_engine(os.environ.get("DB_URI"))
    sess = scoped_session(sessionmaker(bind=engine))
    try:
        yield sess
    finally:
        sess.rollback()
        sess.close()
