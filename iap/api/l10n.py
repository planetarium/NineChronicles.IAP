import os
from typing import Annotated

from fastapi import APIRouter, Header
from starlette.responses import JSONResponse
from starlette.status import HTTP_404_NOT_FOUND

from common import logger
from common.enums import PackageName
from iap.schemas.l10n import L10NSchema

router = APIRouter(
    prefix="/l10n",
    tags=["L10N"],
)

CDN_HOST_DICT = {
    PackageName.NINE_CHRONICLES_M: os.environ.get("CDN_HOST", "http://localhost"),
    PackageName.NINE_CHRONICLES_K: os.environ.get("CDN_HOST_K", "http://localhost"),
}


@router.get("", response_model=L10NSchema)
def l10n_list(x_iap_packagename: Annotated[PackageName | None, Header()]):
    host = CDN_HOST_DICT.get(x_iap_packagename)
    if not host:
        msg = f"No CDN host for package {x_iap_packagename}"
        logger.error(msg)
        return JSONResponse(status_code=HTTP_404_NOT_FOUND, content=msg)

    return L10NSchema(
        host=host,
        category="shop/l10n/category.csv",
        product="shop/l10n/product.csv"
    )
