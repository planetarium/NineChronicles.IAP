from fastapi import APIRouter

from iap.api import history, purchase

router = APIRouter(
    prefix="/api",
    # tags=["API"],
)

__all__ = [
    history,
    purchase,
]

for view in __all__:
    router.include_router(view.router)
