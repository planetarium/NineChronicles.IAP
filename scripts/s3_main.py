import os
from dotenv import load_dotenv

from common.utils.s3 import invalidate_cloudfront, upload_image_to_s3, upload_to_s3

# ✅ .env 파일 로드
load_dotenv()

IMAGES_FOLDER_PATH = os.getenv("IMAGES_FOLDER_PATH", "product/images")

def upload_images_to_s3():
    """ IMAGES_FOLDER_PATH 내의 모든 이미지 파일을 S3에 업로드 """
    if not os.path.exists(IMAGES_FOLDER_PATH):
        print(f"❌ {IMAGES_FOLDER_PATH} 폴더가 존재하지 않습니다. 업로드를 중단합니다.")
        return

    for root, _, files in os.walk(IMAGES_FOLDER_PATH):
        for file in files:
            local_file_path = os.path.join(root, file)
            file_name = os.path.basename(file)

            upload_image_to_s3(local_file_path, file_name)


if __name__ == "__main__":
    print("🚀 S3 파일 업로드 시작...")
    upload_to_s3()

    print("\n🚀 이미지 파일 업로드 시작...")
    upload_images_to_s3()

    print("\n🚀 CloudFront 캐시 무효화 시작...")
    invalidate_cloudfront()

    print("\n✅ 작업 완료!")
