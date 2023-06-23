import os.path

import uvicorn
from fastapi import FastAPI, HTTPException
from mangum import Mangum
from pydantic import ValidationError
from pydantic.error_wrappers import _display_error_type_and_ctx
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_500_INTERNAL_SERVER_ERROR

from common import logger
from . import api, settings
from iap.exceptions import ReceiptNotFoundException

__VERSION__ = "0.1.0"

env = os.environ.get("ENV", "local")

app = FastAPI(
    title="Nine Chronicles In-app Purchase Validation Service",
    description="",
    version=__VERSION__,
    root_path=f"/{env}" if env != "local" else "",
)


@app.exception_handler(ValidationError)
def handle_validation_error(e: ValidationError):
    logger.debug(e)
    ers = e.errors()
    raise HTTPException(
        status_code=HTTP_400_BAD_REQUEST, detail={
            "message": f"{len(ers)} validation errors found",
            "detail": [
                {
                    "location": f"{e['loc']}",
                    "error_type": _display_error_type_and_ctx(e)
                }
                for e in ers
            ],
        }
    )


@app.exception_handler(ValueError)
@app.exception_handler(ReceiptNotFoundException)
def handle_value_error(e: ValueError):
    logger.debug(e)
    raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(e))


@app.exception_handler(Exception)
def handle_exceptions(e: Exception):
    logger.error(e)
    raise HTTPException(
        status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        detail="An unexpected error occurred. Please contact to manager."
    )


@app.get("/ping", tags=["Default"])
def ping():
    """
    This API is for test connectivity.

    This API always returns string "pong" with HTTP status code 200
    """
    return "pong"


@app.get("/robots.txt", response_class=FileResponse, tags=["Default"], summary="Returns robots.txt")
def robots():
    """
    This API returns standard robots.txt file.

    The robots.txt blocks all agent for all routes.
    """
    return "iap/robots.txt"


@app.get("/favicon.png", response_class=FileResponse, tags=["Default"])
def favicon():
    return "iap/frontend/build/favicon.png"


@app.get("/", response_class=FileResponse, tags=["View"], summary="Index page")
@app.get(
    "/{page}", response_class=FileResponse, tags=["View"], summary="Opens pages provided name",
    description="""Frontend pages are controlled by Svelte.  
If you access to any page other than index directly from browser, this function will find right page to show.  

Available page list:
- box
"""
)
def view_page(page: str = "index"):
    # NOTICE: Set html name matches to path.
    if os.path.isfile(f"iap/frontend/build/{page}.html"):
        return f"iap/frontend/build/{page}.html"
    raise HTTPException(status_code=404, detail=f"Page Not Found: /{page}")


app.include_router(api.router)
app.mount("", StaticFiles(directory="iap/frontend/build"))

handler = Mangum(app)

if __name__ == "__main__":
    uvicorn.run("main:app", reload=settings.DEBUG)
