import os

from fastapi import APIRouter, HTTPException
from starlette.responses import FileResponse

router = APIRouter(
    prefix="/views",
    tags=["Views"],
)


@router.get("/", response_class=FileResponse, summary="Index page")
@router.get(
    "/{page}", response_class=FileResponse, summary="Opens pages provided name",
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
