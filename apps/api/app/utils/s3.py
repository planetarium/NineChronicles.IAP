import os

import boto3

from app.config import config

# ✅ S3 버킷 정보
S3_BUCKET = config.s3_bucket

S3_KEYS = ["mainnet/shop/l10n/product.csv", "K/mainnet/shop/l10n/product.csv"]
S3_IMAGE_DETAIL_FOLDER = [
    "mainnet/shop/images/product/detail/",
    "K/mainnet/shop/images/product/detail/",
]
S3_IMAGE_LIST_FOLDER = [
    "mainnet/shop/images/product/list/",
    "K/mainnet/shop/images/product/list/",
]

# ✅ CloudFront 배포 ID
CLOUDFRONT_DISTRIBUTION_1 = config.cloudfront_distribution_1
CLOUDFRONT_DISTRIBUTION_2 = config.cloudfront_distribution_2

# ✅ AWS 클라이언트 설정
s3_client = boto3.client("s3")
cloudfront_client = boto3.client("cloudfront")


def upload_image_to_s3(file_path: str, file_name: str):
    # ✅ `_s`가 포함된 파일은 list 폴더로 업로드 (파일명에서 `_s` 제거)
    if "_s" in file_name:
        upload_folders = S3_IMAGE_LIST_FOLDER
        s3_file_name = file_name.replace("_s", "")
    else:
        upload_folders = S3_IMAGE_DETAIL_FOLDER
        s3_file_name = file_name

    for folder in upload_folders:
        s3_key = folder + s3_file_name
        try:
            s3_client.upload_file(file_path, S3_BUCKET, s3_key)
            print(f"✅ S3 이미지 업로드 완료: s3://{S3_BUCKET}/{s3_key}")
        except Exception as e:
            print(f"❌ S3 이미지 업로드 실패 (s3://{S3_BUCKET}/{s3_key}): {e}")


def invalidate_cloudfront():
    """CloudFront 캐시 무효화"""
    for distribution_id in [CLOUDFRONT_DISTRIBUTION_1, CLOUDFRONT_DISTRIBUTION_2]:
        try:
            response = cloudfront_client.create_invalidation(
                DistributionId=distribution_id,
                InvalidationBatch={
                    "Paths": {"Quantity": 1, "Items": ["/*"]},  # 전체 패스 무효화
                    "CallerReference": str(os.urandom(16)),  # 유니크한 값 사용
                },
            )
            print(f"✅ CloudFront 캐시 무효화 요청 완료: {distribution_id}")
        except Exception as e:
            print(f"❌ CloudFront 캐시 무효화 실패 ({distribution_id}): {e}")


def upload_to_s3(l10n_file_path: str = config.l10n_file_path) -> bool:
    """S3에 product.csv 업로드"""
    if not os.path.exists(l10n_file_path):
        print(f"❌ {l10n_file_path} 파일이 존재하지 않습니다. 업로드를 중단합니다.")
        return False

    success = True
    for s3_key in S3_KEYS:
        try:
            s3_client.upload_file(l10n_file_path, S3_BUCKET, s3_key)
            print(f"✅ S3 업로드 완료: s3://{S3_BUCKET}/{s3_key}")
        except Exception as e:
            print(f"❌ S3 업로드 실패 (s3://{S3_BUCKET}/{s3_key}): {e}")
            success = False
    return success
