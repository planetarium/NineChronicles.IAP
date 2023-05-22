from fastapi import APIRouter

from iap.api import box, item

router = APIRouter(
    prefix="/api",
    # tags=["API"],
)

__all__ = [
    box,
    item,
]

for view in __all__:
    router.include_router(view.router)
