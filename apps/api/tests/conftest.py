"""
API 테스트 부트스트랩 — `shared` 설치본이 스테일하면 리포의 `apps/shared` 를 sys.path 앞에 둔다.

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
import sys
from pathlib import Path

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
