import os
import boto3
from dotenv import load_dotenv

# ✅ .env 파일 로드
load_dotenv()

# ✅ S3 버킷 정보
S3_BUCKET = os.getenv("S3_BUCKET")
S3_KEYS = [
    "mainnet/shop/l10n/product.csv",
    "K/mainnet/shop/l10n/product.csv"
]
S3_IMAGE_DETAIL_FOLDER = [
    "mainnet/shop/images/product/detail/",
    "K/mainnet/shop/images/product/detail/"
]
S3_IMAGE_LIST_FOLDER = [
    "mainnet/shop/images/product/list/",
    "K/mainnet/shop/images/product/list/"
]

L10N_FILE_PATH = os.getenv("L10N_FILE_PATH", "product.csv")
IMAGES_FOLDER_PATH = os.getenv("IMAGES_FOLDER_PATH", "product/images")

# ✅ CloudFront 배포 ID
CLOUDFRONT_DISTRIBUTION_1 = os.getenv("CLOUDFRONT_DISTRIBUTION_1")
CLOUDFRONT_DISTRIBUTION_2 = os.getenv("CLOUDFRONT_DISTRIBUTION_2")

# ✅ AWS 클라이언트 설정
s3_client = boto3.client("s3")
cloudfront_client = boto3.client("cloudfront")

def upload_to_s3():
    """ S3에 product.csv 업로드 """
    if not os.path.exists(L10N_FILE_PATH):
        print(f"❌ {L10N_FILE_PATH} 파일이 존재하지 않습니다. 업로드를 중단합니다.")
        return

    for s3_key in S3_KEYS:
        try:
            s3_client.upload_file(L10N_FILE_PATH, S3_BUCKET, s3_key)
            print(f"✅ S3 업로드 완료: s3://{S3_BUCKET}/{s3_key}")
        except Exception as e:
            print(f"❌ S3 업로드 실패 (s3://{S3_BUCKET}/{s3_key}): {e}")

def upload_images_to_s3():
    """ IMAGES_FOLDER_PATH 내의 모든 이미지 파일을 S3에 업로드 """
    if not os.path.exists(IMAGES_FOLDER_PATH):
        print(f"❌ {IMAGES_FOLDER_PATH} 폴더가 존재하지 않습니다. 업로드를 중단합니다.")
        return

    for root, _, files in os.walk(IMAGES_FOLDER_PATH):
        for file in files:
            local_file_path = os.path.join(root, file)
            file_name = os.path.basename(file)

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
                    s3_client.upload_file(local_file_path, S3_BUCKET, s3_key)
                    print(f"✅ S3 이미지 업로드 완료: s3://{S3_BUCKET}/{s3_key}")
                except Exception as e:
                    print(f"❌ S3 이미지 업로드 실패 (s3://{S3_BUCKET}/{s3_key}): {e}")

def invalidate_cloudfront():
    """ CloudFront 캐시 무효화 """
    for distribution_id in [CLOUDFRONT_DISTRIBUTION_1, CLOUDFRONT_DISTRIBUTION_2]:
        try:
            response = cloudfront_client.create_invalidation(
                DistributionId=distribution_id,
                InvalidationBatch={
                    "Paths": {"Quantity": 1, "Items": ["/*"]},  # 전체 패스 무효화
                    "CallerReference": str(os.urandom(16))  # 유니크한 값 사용
                }
            )
            print(f"✅ CloudFront 캐시 무효화 요청 완료: {distribution_id}")
        except Exception as e:
            print(f"❌ CloudFront 캐시 무효화 실패 ({distribution_id}): {e}")

if __name__ == "__main__":
    print("🚀 S3 파일 업로드 시작...")
    upload_to_s3()

    print("\n🚀 이미지 파일 업로드 시작...")
    upload_images_to_s3()

    print("\n🚀 CloudFront 캐시 무효화 시작...")
    invalidate_cloudfront()

    print("\n✅ 작업 완료!")
