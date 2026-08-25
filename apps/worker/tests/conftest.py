"""
워커 테스트 부트스트랩 — 이게 없으면 테스트 **수집**이 실패한다. 걸림돌 두 개를 치운다.

1. `app.config.Settings()` 가 모듈 임포트 시점에 평가되고 필수값 `kms_key_id` 가 있다.
   실제 KMS 를 쓰는 테스트는 없으므로 더미를 심어 임포트만 통과시킨다.
2. `shared` 가 non-editable path 의존성(`pyproject.toml`: shared = { path = "../shared" })이라
   venv 안에 **복사본**으로 깔린다. 그래서 `apps/shared` 에 모듈이 추가돼도 재설치 전까지
   `ModuleNotFoundError: shared.models.…` 가 난다. 정답은 재설치(`poetry install`)지만 그걸
   모르면 "테스트가 깨졌다"로 오해하기 쉬워서, 설치본이 스테일할 때만 리포의 apps/shared 를
   sys.path 앞에 두고 경고를 찍는다(조용히 덮지 않는다).

   ⚠️ 판정은 **파일 존재**로 한다. `import shared.…` 로 확인하면 그 시점에 부모 패키지가
   스테일 경로로 sys.modules 에 박혀서, 뒤늦게 sys.path 를 바꿔도 서브모듈을 못 찾는다.

이 저장소 CI(.github/workflows/build_docker.yml)는 pytest 를 돌리지 않는다 — 로컬 실행이 유일하다.
"""
import os
import sys
import sysconfig
from pathlib import Path

os.environ.setdefault("WORKER_KMS_KEY_ID", "test-dummy-key")

_CANARY = Path("shared") / "models" / "product_voucher_grant.py"
_repo_shared = Path(__file__).resolve().parents[2] / "shared"
_installed = Path(sysconfig.get_paths()["purelib"]) / _CANARY

if not _installed.exists() and (_repo_shared / _CANARY).exists():
    sys.path.insert(0, str(_repo_shared))
    print(
        f"[conftest] venv 의 shared 설치본이 스테일합니다 → {_repo_shared} 를 sys.path 앞에 둡니다."
        " 영구 해결은 `cd apps/worker && poetry install`.",
        file=sys.stderr,
    )
