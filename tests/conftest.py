import os
import sys
from contextlib import contextmanager
from typing import List

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session, make_transient

# Python 경로에 apps/shared 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'apps', 'shared'))

from shared.models.product import Product
from shared.models.receipt import Receipt


@pytest.fixture(scope="session", autouse=True)
def setup_python_path():
    """Python 경로 설정"""
    # apps/shared를 Python 경로에 추가
    shared_path = os.path.join(os.path.dirname(__file__), '..', 'apps', 'shared')
    if shared_path not in sys.path:
        sys.path.insert(0, shared_path)


@pytest.fixture(scope="session", autouse=True)
def setup_alembic(setup_python_path):
    """Alembic 설정 - 환경변수가 설정된 경우에만 실행"""
    if os.environ.get('DB_URI') and os.environ.get('DB_URI') != 'sqlite:///:memory:':
        try:
            from alembic import command
            from alembic.config import Config

            db_uri = os.environ.get('DB_URI', '')
            config = Config("apps/shared/alembic.ini")
            config.set_main_option("script_location", "apps/shared/tool/migrations")
            config.set_main_option("sqlalchemy.url", db_uri)

            command.upgrade(config, "head")
            yield
            command.downgrade(config, "base")
        except Exception as e:
            print(f"Alembic 설정 실패 (무시됨): {e}")
            yield
    else:
        # 메모리 DB 또는 DB_URI가 없는 경우 alembic 설정 건너뛰기
        yield


@pytest.fixture(scope="function")
def session(setup_alembic):
    db_uri = os.environ.get("DB_URI", "sqlite:///:memory:")
    engine = create_engine(db_uri)
    sess = scoped_session(sessionmaker(bind=engine))
    try:
        yield sess
    finally:
        sess.rollback()
        sess.close()


@contextmanager
def add_product(sess, product_list: List[Product]):
    try:
        for product in product_list:
            make_transient(product)
            sess.add(product)
        sess.commit()
        for p in product_list:
            sess.refresh(p)
        yield product_list
    finally:
        for product in product_list:
            sess.delete(product)
        sess.commit()


@contextmanager
def add_receipt(sess, receipt_list: List[Receipt]):
    try:
        for receipt in receipt_list:
            sess.add(receipt)
        sess.commit()
        for r in receipt_list:
            sess.refresh(r)
        yield receipt_list
    finally:
        for receipt in receipt_list:
            sess.delete(receipt)
        sess.commit()
