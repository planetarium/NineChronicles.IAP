import os

from fastapi import APIRouter
from starlette.responses import JSONResponse
from starlette.status import HTTP_404_NOT_FOUND

from common import logger
from iap.schemas.l10n import L10NSchema

router = APIRouter(
    prefix="/l10n",
    tags=["L10N"],
)

CDN_HOST_DICT = {
    "com.planetariumlabs.ninechroniclesmobile": os.environ.get("CDN_HOST", "http://localhost"),
    "com.planetariumlabs.ninek": os.environ.get("CDN_HOST_K", "http://localhost"),
}


@router.get("", response_model=L10NSchema)
def l10n_list(package_name: str):
    host = CDN_HOST_DICT.get(package_name)
    if not host:
        msg = f"No CDN host for package {package_name}"
        logger.error(msg)
        return JSONResponse(status_code=HTTP_404_NOT_FOUND, content=msg)

    return L10NSchema(
        host=CDN_HOST_DICT.get(package_name),
        category="shop/l10n/category.csv",
        product="shop/l10n/product.csv"
    )
