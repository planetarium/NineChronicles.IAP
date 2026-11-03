import os
import sys
from contextlib import contextmanager
from typing import List

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, make_transient

# apps/api/app/config 를 임포트하는 테스트용 더미 env — apps/api/tests/conftest.py 와 같은 값.
#   테스트 모듈 임포트보다 먼저 채워져야 하고, setdefault 라 실제 값이 있는 환경은 덮지 않는다.
for _key, _value in {
    "API_BACKOFFICE_JWT_SECRET": "test-secret",
    "API_SEASON_PASS_HOST": "http://localhost",
    "API_SEASON_PASS_JWT_SECRET": "x",
    "API_GOOGLE_CREDENTIAL": "x",
    "API_APPLE_CREDENTIAL": "x",
    "API_APPLE_BUNDLE_ID": "x",
    "API_APPLE_KEY_ID": "x",
    "API_APPLE_ISSUER_ID": "x",
    "API_APPLE_VALIDATION_URL": "http://localhost",
    "API_STRIPE_SECRET_KEY": "x",
    "API_STRIPE_TEST_SECRET_KEY": "x",
    "API_CLOUDFLARE_API_KEY": "x",
    "API_CLOUDFLARE_ASSETS_K_ZONE_ID": "x",
    "API_CLOUDFLARE_ASSETS_ZONE_ID": "x",
    "API_CLOUDFLARE_EMAIL": "x@example.com",
    "API_R2_ACCESS_KEY_ID": "x",
    "API_R2_ACCOUNT_ID": "x",
    "API_R2_BUCKET": "x",
    "API_R2_SECRET_ACCESS_KEY": "x",
    "API_S3_BUCKET": "x",
    "API_CLOUDFRONT_DISTRIBUTION_1": "x",
    "API_CLOUDFRONT_DISTRIBUTION_2": "x",
    "API_REDEEM_API_BASE_URL": "http://localhost",
}.items():
    os.environ.setdefault(_key, _value)

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


# 테스트 전용 이름 — scripts/ 의 운영 스크립트가 DB_URI 를 쓰므로 그게 셸에 남아 있어도 여기로 새지 않게.
TEST_DB_URI = os.environ.get("TEST_DB_URI")
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(scope="session")
def db_engine():
    """Postgres 가 필요한 테스트용 엔진 — TEST_DB_URI 의 DB 를 alembic 으로 head 까지 올린다.

    TEST_DB_URI 가 없으면(로컬에 DB 가 없을 때) 그 테스트들은 건너뛴다. CI(.github/workflows/test.yml)는
    Postgres 서비스를 붙여 TEST_DB_URI 를 준다 — 거기선 반드시 돈다. JSONB 등 Postgres 전용 타입이 있어
    SQLite 로는 테이블을 만들 수 없다.
    """
    if not TEST_DB_URI or TEST_DB_URI.startswith("sqlite"):
        if os.environ.get("CI"):
            pytest.fail("CI 인데 TEST_DB_URI(Postgres) 가 없다 — DB 테스트가 조용히 건너뛰어진다")
        pytest.skip("TEST_DB_URI(Postgres) 없음 — DB 테스트는 CI 에서 돈다")
    if "test" not in TEST_DB_URI.rsplit("/", 1)[-1]:
        pytest.exit("TEST_DB_URI 의 DB 이름에 'test' 가 없다 — 마이그레이션(DDL)을 돌리므로 테스트 DB 만 쓴다", returncode=2)
    from alembic import command
    from alembic.config import Config

    os.environ["DATABASE_URI"] = TEST_DB_URI  # tool/migrations/env.py 가 이 이름으로 읽는다
    config = Config(os.path.join(REPO_ROOT, "apps", "shared", "alembic.ini"))
    config.set_main_option("script_location", os.path.join(REPO_ROOT, "apps", "shared", "tool", "migrations"))
    command.upgrade(config, "head")  # 실패하면 그대로 실패한다(예전엔 삼켜서 DB 테스트가 엉뚱하게 깨졌다)
    engine = create_engine(TEST_DB_URI)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    """테스트마다 바깥 트랜잭션을 열고 끝에 되돌린다 — 테스트 안의 commit 은 savepoint 로만 남아 DB 가 깨끗하게 유지된다."""
    conn = db_engine.connect()
    outer = conn.begin()
    sess = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        yield sess
    finally:
        sess.close()
        outer.rollback()
        conn.close()


@pytest.fixture
def session(db_session):
    """예전 이름 — db_session 과 같다."""
    yield db_session


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
