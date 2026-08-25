"""
워커 테스트 부트스트랩 — 이게 없으면 테스트 **수집**이 실패한다. 걸림돌 두 개를 치운다.

1. `app.config.Settings()` 가 모듈 임포트 시점에 평가되고 필수값 `kms_key_id` 가 있다.
   실제 KMS 를 쓰는 테스트는 없으므로 더미를 심어 임포트만 통과시킨다. 웹훅 URL 은 `.env` 가
   있는 개발자 환경에서 실 엔드포인트를 물고 돌 수 있어 **강제로 비운다**(setdefault 아님).
2. `shared` 가 non-editable path 의존성(`pyproject.toml`: shared = { path = "../shared" })이라
   venv 안에 **복사본**으로 깔린다. 그래서 `apps/shared` 에 모듈이 추가돼도 재설치 전까지
   `ModuleNotFoundError: shared.models.…` 가 난다. 정답은 재설치(`poetry install`)지만 그걸
   모르면 "테스트가 깨졌다"로 오해하기 쉬워서, 설치본이 스테일할 때만 리포의 apps/shared 를
   sys.path 앞에 두고 경고를 찍는다(조용히 덮지 않는다).

   판정은 `find_spec("shared")` 로 **설치 위치만** 얻어서(최상위 이름이라 import 가 일어나지
   않는다) 리포의 `shared/**/*.py` 와 대조한다. `import shared.models.…` 로 판정하면 그 시점에
   부모 패키지가 스테일 경로로 sys.modules 에 박혀서 뒤늦은 sys.path 삽입이 무효가 된다.
   특정 모듈을 canary 로 하드코딩하지 않는 이유는 다음에 추가되는 모듈에서 또 새기 때문이다.

⚠️ 알려진 선행 실패: `test_track_google_refund` 4건은 이 conftest 로 처음 실행되면서 드러난
   기존 문제다(`VoidReason` 에 없는 멤버 단정, `google_package_dict` 키 타입 불일치). main
   에서도 동일하게 실패하며 바우처 변경과 무관하다 — 자기 변경 탓으로 오해하지 말 것.

이 저장소 CI(.github/workflows/build_docker.yml)는 pytest 를 돌리지 않는다 — 로컬 실행이 유일하다.
"""
import importlib.util
import os
import sys
from pathlib import Path

os.environ.setdefault("WORKER_KMS_KEY_ID", "test-dummy-key")
for _leaky in ("WORKER_IAP_ALERT_WEBHOOK_URL", "WORKER_IAP_GARAGE_WEBHOOK_URL"):
    os.environ[_leaky] = ""

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


_installed_root = _installed_shared_root()
if _installed_root is not None:
    _missing = [
        rel
        for rel in (
            p.relative_to(_repo_shared) for p in (_repo_shared / "shared").rglob("*.py")
        )
        if not (_installed_root / rel).exists()
    ]
    if _missing:
        sys.path.insert(0, str(_repo_shared))
        print(
            f"[conftest] {_installed_root} 의 shared 설치본이 스테일합니다"
            f" (누락 {len(_missing)}개, 예: {_missing[0]}) → {_repo_shared} 를 sys.path 앞에 둡니다."
            " 영구 해결은 `cd apps/worker && poetry install`.",
            file=sys.stderr,
        )
