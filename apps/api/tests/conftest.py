"""
API 테스트 부트스트랩 — 두 가지를 한다.
  1. `app.config.Settings` 가 요구하는 필수 env 를 더미로 채운다(실 앱 `main.app` 을 띄우는
     테스트가 임포트 시점에 죽지 않게). 아래 `os.environ.setdefault` 블록.
  2. `shared` 설치본이 스테일하면 리포의 `apps/shared` 를 sys.path 앞에 둔다(이하 설명).

`shared` 는 non-editable path 의존성(`pyproject.toml`: shared = { path = "../shared" })이라 venv 안에
**복사본**으로 깔린다. 그래서 `apps/shared` 를 고쳐도 재설치 전까지 테스트는 옛 코드를 임포트한다.
증상이 두 가지인데 둘째가 더 나쁘다:
  - 새 모듈 추가 → `ModuleNotFoundError: shared.models.…` (요란해서 금방 눈치챈다)
  - 기존 모듈 수정 → **조용히** 옛 정의로 통과/실패 (예: schemas/product.py 에 필드를 추가해도 안 보인다)

워커 conftest(`apps/worker/tests/conftest.py`)와 같은 문제·같은 처방이지만 **판정 범위가 다르다.**
거기는 파일 누락만 보고, 여기는 내용 불일치까지 본다 — 이 디렉터리의 테스트가 기존 모듈 수정
(스키마 필드 추가)을 검증하기 때문이다. 조용히 덮지 않고 stderr 로 알린다. 영구 해결은
`cd apps/api && poetry install`.

판정에 `find_spec("shared")` 를 쓰는 이유: 최상위 이름이라 **임포트를 일으키지 않고** 설치 위치만
얻는다. `import shared.…` 로 판정하면 그 시점에 스테일 경로가 sys.modules 에 박혀 뒤늦은 sys.path
삽입이 무효가 된다.

실행은 반드시 `cd apps/api && .venv/bin/python -m pytest tests/ -q`. `-m pytest` 여야 cwd 가 sys.path 에
들어가 `import app` 이 풀린다(`pytest tests/` 로 부르면 수집 단계에서 깨진다). cwd 가 apps/api 여야
`app.config` 의 `.env` 도 같이 읽힌다.

이 저장소 CI(.github/workflows/build_docker.yml)는 pytest 를 돌리지 않는다 — 로컬 실행이 유일하다.
"""
import importlib.util
import os
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import event

# `main`/`app.config` 를 임포트하는 테스트용 더미 env. `app.config.Settings` 는 필수 값이 많아
#   임포트 시점에 죽으므로 **테스트 모듈 임포트보다 먼저** 채워져 있어야 한다(conftest 는 항상
#   먼저 로드된다). `setdefault` 라 실제 값이 있는 환경은 덮지 않는다.
#   ⚠️ 이게 로컬 `.env` 문제를 해결해 주진 않는다 — env var 가 .env 보다 우선이긴 하지만,
#      .env 에 현재 Settings 가 모르는 **옛 키**가 남아 있으면 `extra_forbidden` 으로 여전히
#      임포트가 죽는다. 그래서 config 를 아예 임포트하지 않는 테스트도 있다
#      (`test_product_voucher_tickets.py` 의 `product_api` 픽스처).
#   (`test_admin_grant.py` 는 모듈 안에 같은 블록을 갖고 있다 — 이제 중복이지만 setdefault 라
#    무해하고, 그 파일 단독 실행 시의 자기완결성을 남겨 둔다.)
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

_repo_shared = Path(__file__).resolve().parents[2] / "shared"


def _installed_shared_root() -> Path | None:
    """설치된 `shared` 패키지의 부모 디렉터리. 못 찾으면 None(스테일 판정 스킵)."""
    try:
        spec = importlib.util.find_spec("shared")
    except (ImportError, ValueError):
        return None
    locations = list(getattr(spec, "submodule_search_locations", None) or [])
    if not locations:
        return None
    root = Path(locations[0]).parent
    # 이미 리포를 보고 있으면(editable/PYTHONPATH) 스테일일 수 없다.
    return None if root == _repo_shared else root


def _stale_files(installed_root: Path) -> list[Path]:
    """리포와 설치본이 다른(또는 없는) `shared/**/*.py` 상대경로 목록."""
    stale = []
    for path in (_repo_shared / "shared").rglob("*.py"):
        rel = path.relative_to(_repo_shared)
        installed = installed_root / rel
        if not installed.exists() or installed.read_bytes() != path.read_bytes():
            stale.append(rel)
    return stale


_installed_root = _installed_shared_root()
if _installed_root is not None:
    _stale = _stale_files(_installed_root)
    if _stale:
        sys.path.insert(0, str(_repo_shared))
        print(
            f"[conftest] {_installed_root} 의 shared 설치본이 스테일합니다"
            f" (불일치 {len(_stale)}개, 예: {_stale[0]}) → {_repo_shared} 를 sys.path 앞에 둡니다."
            " 영구 해결은 `cd apps/api && poetry install`.",
            file=sys.stderr,
        )


@pytest.fixture
def count_select():
    """
    블록 안에서 나간 SELECT 수를 세는 컨텍스트매니저 팩토리. N+1 회귀를 숫자로 못박는 용도.

    `count_select(engine, table="product_voucher_grant")` 처럼 테이블을 주면 그 테이블을 건드린
    SELECT 만 센다 — 엔드포인트에는 측정 대상과 무관한 선행 lazy load(예: `price_list`)가 있어서
    전체 수를 세면 보증하려는 것과 다른 걸 재게 된다.
    """

    @contextmanager
    def _count(engine, table: str = ""):
        counter = {"n": 0}

        def _before(conn, cursor, statement, parameters, context, executemany):
            if not statement.lstrip().upper().startswith("SELECT"):
                return
            if table and table not in statement:
                return
            counter["n"] += 1

        event.listen(engine, "before_cursor_execute", _before)
        try:
            yield counter
        finally:
            event.remove(engine, "before_cursor_execute", _before)

    return _count
