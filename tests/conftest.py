import os
from contextlib import contextmanager
from typing import List

import alembic
import pytest
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session

from common.models.product import Product
from common.models.receipt import Receipt


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


@contextmanager
def add_product(sess, product_list: List[Product]):
    try:
        for product in product_list:
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
