import os.path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from mangum import Mangum
from pydantic.v1.error_wrappers import _display_error_type_and_ctx
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.staticfiles import StaticFiles
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_500_INTERNAL_SERVER_ERROR

from common import logger
from iap.exceptions import ReceiptNotFoundException
from . import api, views, settings

__VERSION__ = "0.1.0"

stage = os.environ.get("STAGE", "local")

app = FastAPI(
    title="Nine Chronicles In-app Purchase Validation Service",
    description="",
    version=__VERSION__,
    debug=settings.DEBUG,
)


@app.middleware("http")
async def log_request_response(request: Request, call_next):
    logger.info(f"[{request.method}] {request.url}")
    response = await call_next(request)
    if response.status_code == 200:
        logger.info(f"Request success with {response.status_code}")
    else:
        logger.error(f"Request failed with {response.status_code}")
    return response


# Error handler
@app.exception_handler(RequestValidationError)
def handle_validation_error(request: Request, e: RequestValidationError):
    logger.error(e)
    ers = e.errors()
    return JSONResponse(
        status_code=HTTP_400_BAD_REQUEST,
        content={
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


def handle_400(e):
    logger.error(e)
    return JSONResponse(status_code=HTTP_400_BAD_REQUEST, content=str(e))


@app.exception_handler(ValueError)
def handle_value_error(request: Request, e: ValueError):
    return handle_400(e)


@app.exception_handler(ReceiptNotFoundException)
def handle_receipt_not_found(request: Request, e: ReceiptNotFoundException):
    return handle_400(e)


@app.exception_handler(Exception)
def handle_500(request, e):
    """
    This can cause Exception inside itself: Please track https://github.com/tiangolo/fastapi/discussions/8647
    """
    return JSONResponse(status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                        content=f"An unexpected error occurred. Please contact to administrator. :: {str(e)}")


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


app.include_router(api.router)
app.include_router(views.router)
app.mount("/views/_app", StaticFiles(directory="iap/frontend/build/_app"), name="static")

handler = Mangum(app)

if __name__ == "__main__":
    uvicorn.run("main:app", reload=settings.DEBUG)
