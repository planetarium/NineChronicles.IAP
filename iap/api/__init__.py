from fastapi import APIRouter

from iap.api import item

router = APIRouter(
    prefix="/api",
    # tags=["API"],
)

__all__ = [
    item,
]

for view in __all__:
    router.include_router(view.router)
