from fastapi import APIRouter

from iap.api import history

router = APIRouter(
    prefix="/api",
    # tags=["API"],
)

__all__ = [
    history,
]

for view in __all__:
    router.include_router(view.router)
