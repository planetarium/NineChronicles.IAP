from fastapi import APIRouter

from iap.api import history, purchase, product, admin, l10n, mileage

router = APIRouter(
    prefix="/api",
    # tags=["API"],
)

__all__ = [
    history,
    purchase,
    product,
    l10n,
    mileage,
    admin,
]

for view in __all__:
    router.include_router(view.router)
