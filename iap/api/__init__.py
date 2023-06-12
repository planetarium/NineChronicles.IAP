from fastapi import APIRouter

from iap.api import box, item, history

router = APIRouter(
    prefix="/api",
    # tags=["API"],
)

__all__ = [
    box,
    item,
    history,
]

for view in __all__:
    router.include_router(view.router)
