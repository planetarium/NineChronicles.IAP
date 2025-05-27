import os
from typing import Annotated

import structlog
from fastapi import APIRouter, Header
from shared.enums import PackageName
from shared.schemas.l10n import L10NSchema
from starlette.responses import JSONResponse
from starlette.status import HTTP_404_NOT_FOUND

from app.config import config

router = APIRouter(
    prefix="/l10n",
    tags=["L10N"],
)

logger = structlog.get_logger(__name__)


@router.get("", response_model=L10NSchema)
def l10n_list(
    x_iap_packagename: Annotated[
        PackageName | None, Header()
    ] = PackageName.NINE_CHRONICLES_M,
):
    host = config.cdn_host_map.get(x_iap_packagename.value)
    if not host:
        msg = f"No CDN host for package {x_iap_packagename.value}"
        logger.error(msg)
        return JSONResponse(status_code=HTTP_404_NOT_FOUND, content=msg)

    return L10NSchema(
        host=host, category="shop/l10n/category.csv", product="shop/l10n/product.csv"
    )
