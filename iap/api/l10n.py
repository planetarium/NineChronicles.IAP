import os

from fastapi import APIRouter

from iap.schemas.l10n import L10NSchema

router = APIRouter(
    prefix="/l10n",
    tags=["L10N"],
)


@router.get("", response_model=L10NSchema)
def l10n_list():
    return L10NSchema(
        host=os.environ.get("CDN_HOST", "http://localhost"),
        category="shop/l10n/category.csv",
        product="shop/l10n/product.csv"
    )
