from fastapi import APIRouter, Request, Depends, HTTPException
from starlette.responses import RedirectResponse
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import os

router = APIRouter(prefix="/auth")

# Google OAuth 설정
GOOGLE_CLIENT_ID = os.getenv("BACKOFFICE_OAUTH_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("BACKOFFICE_OAUTH_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("BACKOFFICE_OAUTH_REDIRECT_URI", "http://localhost:8000/auth/callback")

# 허용된 이메일 도메인
ALLOWED_DOMAINS = ["planetariumhq.com"]

# OAuth 설정
flow = Flow.from_client_config(
    {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [GOOGLE_REDIRECT_URI]
        }
    },
    scopes=[
        "openid",
        "https://www.googleapis.com/auth/userinfo.profile",
        "https://www.googleapis.com/auth/userinfo.email"
    ]
)

@router.get("/login")
async def login(request: Request):
    # 로그인 상태 확인
    if request.session.get("user"):
        return RedirectResponse(url="/products")

    # Google 로그인 URL 생성
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true"
    )

    # 상태 저장
    request.session["state"] = state
    return RedirectResponse(url=authorization_url)

@router.get("/callback")
async def callback(request: Request, code: str, state: str):
    # 상태 검증
    if state != request.session.get("state"):
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    # 인증 코드로 토큰 획득
    flow.fetch_token(code=code)
    credentials = flow.credentials

    # 사용자 정보 획득
    service = build('oauth2', 'v2', credentials=credentials)
    user_info = service.userinfo().get().execute()

    # 이메일 도메인 검증
    email = user_info.get("email")
    domain = email.split("@")[1]
    if domain not in ALLOWED_DOMAINS:
        raise HTTPException(status_code=403, detail="Unauthorized email domain")

    # 세션에 사용자 정보 저장
    request.session["user"] = {
        "email": email,
        "name": user_info.get("name"),
        "picture": user_info.get("picture")
    }

    return RedirectResponse(url="/products")

@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/auth/login")