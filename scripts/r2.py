import boto3
import requests

from iap.settings import CLOUDFLARE_API_KEY, CLOUDFLARE_ASSETS_K_ZONE_ID, CLOUDFLARE_ASSETS_ZONE_ID, CLOUDFLARE_EMAIL, R2_ACCESS_KEY_ID, R2_ACCOUNT_ID, R2_BUCKET, R2_SECRET_ACCESS_KEY

CDN_URLS = {
    CLOUDFLARE_ASSETS_ZONE_ID: "https://assets-internal.nine-chronicles.com",
    CLOUDFLARE_ASSETS_K_ZONE_ID: "https://assets-k-internal.nine-chronicles.com"
}


# ✅ R2 버킷 정보
R2_PRODUCT_KEYS = [
    "shop/l10n/product.csv",
]

R2_CATEGORY_KEYS = [
    "shop/l10n/category.csv",
]

R2_IMAGE_DETAIL_FOLDER = [
    "shop/images/product/detail/",
]
R2_IMAGE_LIST_FOLDER = [
    "shop/images/product/list/",
]


# ✅ R2 클라이언트 설정
r2_client = boto3.client(
    "s3",
    endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    region_name="auto",
)

def upload_csv_to_r2(file_path: str, r2_key: str):
    try:
        r2_client.upload_file(
            file_path,
            R2_BUCKET,
            r2_key,
            ExtraArgs={
                "ContentType": "text/csv; charset=utf-8",
                "ContentDisposition": "inline"
            }
        )
        print(f"✅ R2 업로드 완료: r2://{R2_BUCKET}/{r2_key}")
    except Exception as e:
        print(f"❌ R2 업로드 실패 (r2://{R2_BUCKET}/{r2_key}): {e}")

def upload_image_to_r2(file_path: str, r2_key: str):
    try:
        r2_client.upload_file(
            file_path,
            R2_BUCKET,
            r2_key,
            ExtraArgs={
                "ContentType": "image/png",
            }
        )
        print(f"✅ R2 업로드 완료: r2://{R2_BUCKET}/{r2_key}")
    except Exception as e:
        print(f"❌ R2 업로드 실패 (r2://{R2_BUCKET}/{r2_key}): {e}")

def purge_cache(zone_id: str, cdn_url: str, resource_path: str):
    """ r2 캐시 무효화 """
    headers = {
        "X-Auth-Email": CLOUDFLARE_EMAIL,
        "X-Auth-Key": CLOUDFLARE_API_KEY,
        "Content-Type": "application/json"
    }

    cdn_path = f"{cdn_url}/{resource_path}"

    try:
        response = requests.post(
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/purge_cache",
            headers=headers,
            json={
                "zone_id": zone_id,
                "files": [cdn_path],
            }
        )
        result = response.json()
        success = result["success"]

        print(f"📡 API 응답:")
        print(f"상태 코드: {response.status_code}")
        print(f"응답 내용: {result}")
        print(f"성공 여부: {success}")
        if not success:
            print(f"에러 내용: {result.get('errors', '알 수 없음')}")
        if 'messages' in result:
            print(f"메시지: {result['messages']}")
        if 'result' in result:
            print(f"결과: {result['result']}")

        if success:
            print(f"✅ Cloudflare 캐시 무효화 요청 완료: {cdn_path}")
        else:
            print(f"❌ Cloudflare 캐시 무효화 실패 ({cdn_path})")
        return success
    except Exception as e:
        print(f"❌ Cloudflare 캐시 무효화 실패 ({cdn_path}): {e}")
        return False
