import logging

import uvicorn
from fastapi import FastAPI
from starlette.responses import FileResponse

from api import settings

__VERSION__ = "0.1.0"

app = FastAPI(
    title="Nine Chronicles In-app Purchase Validation Service",
    description="",
    version=__VERSION__,
    root_path=f"/",
)


@app.get("/ping", tags=["Default"])
def ping():
    """
    # Ping
    ---
    This API is for test connectivity.

    This API always returns string "pong" with HTTP status code 200
    """
    return "pong"


@app.get("/robots.txt", response_class=FileResponse, tags=["Default"])
def robots():
    """
    # robots.txt: Disallow bots
    ---
    This API returns standard robots.txt file.
    The robots.txt blocks all agent for all routes.
    """
    return "api/robots.txt"


logger = logging.getLogger()
logger.setLevel(settings.LOGGING_LEVEL)

if __name__ == "__main__":
    uvicorn.run("main:app", reload=settings.DEBUG)
