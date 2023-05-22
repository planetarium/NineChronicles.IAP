import logging
import os.path

import uvicorn
from fastapi import FastAPI, HTTPException
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles

from iap import api, settings

__VERSION__ = "0.1.0"

app = FastAPI(
    title="Nine Chronicles In-app Purchase Validation Service",
    description="",
    version=__VERSION__,
    root_path="/",
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
    return "api/robots.txt"


@app.get("/favicon.png", response_class=FileResponse, tags=["Default"])
def favicon():
    return "frontend/build/favicon.png"


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
    if os.path.isfile(f"frontend/build/{page}.html"):
        return f"frontend/build/{page}.html"
    raise HTTPException(status_code=404, detail=f"Page Not Found: /{page}")


logger = logging.getLogger()
logger.setLevel(settings.LOGGING_LEVEL)

app.include_router(api.router)
app.mount("", StaticFiles(directory="frontend/build"))

if __name__ == "__main__":
    uvicorn.run("main:app", reload=settings.DEBUG)
