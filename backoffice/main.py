from fastapi import FastAPI, Depends, Request, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from scripts.s3 import S3_BUCKET, S3_KEYS, S3_IMAGE_DETAIL_FOLDER, S3_IMAGE_LIST_FOLDER, invalidate_cloudfront
from .database import SessionLocal
from common.models.product import Product, Category, FungibleItemProduct, FungibleAssetProduct
from common.enums import ProductType, ProductRarity, ProductAssetUISize
from datetime import datetime
from fastapi import HTTPException
import os
import shutil
import boto3

# AWS 클라이언트 설정
s3_client = boto3.client("s3")
cloudfront_client = boto3.client("cloudfront")

S3_CATEGORY_KEYS = [
    "internal/shop/l10n/category.csv",
    "K/internal/shop/l10n/category.csv"
]

app = FastAPI(debug=True)
templates = Jinja2Templates(directory="backoffice/templates", auto_reload=True)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ✅ Product 목록 조회
@app.get("/products")
def list_products(request: Request, db: Session = Depends(get_db)):
    products = db.query(Product).all()
    categories = db.query(Category).all()

    # Product 데이터 변환
    products_dict = []
    for product in products:
        product_dict = product.to_dict()
        # category_id 설정 (첫 번째 카테고리 사용)
        if product.category_list and len(product.category_list) > 0:
            product_dict['category_id'] = product.category_list[0].id
        products_dict.append(product_dict)


    categories_dict = [category.to_dict() for category in categories]
    return templates.TemplateResponse("products.html", {"request": request, "products": products_dict, "categories": categories_dict})

# ✅ Product 추가/수정 처리
@app.post("/products/save")
async def save_product(
    request: Request,
    detail_image: UploadFile = File(None),
    list_image: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    form_data = await request.form()
    id = form_data.get("id")
    name = form_data.get("name")
    order = int(form_data.get("order"))
    google_sku = form_data.get("google_sku")
    apple_sku = form_data.get("apple_sku")
    apple_sku_k = form_data.get("apple_sku_k")
    product_type = form_data.get("product_type")
    required_level = int(form_data.get("required_level")) if form_data.get("required_level") else None
    daily_limit = int(form_data.get("daily_limit")) if form_data.get("daily_limit") else None
    weekly_limit = int(form_data.get("weekly_limit")) if form_data.get("weekly_limit") else None
    account_limit = int(form_data.get("account_limit")) if form_data.get("account_limit") else None
    active = form_data.get("active") == "on"
    discount = float(form_data.get("discount", 0))
    open_timestamp = form_data.get("open_timestamp")
    close_timestamp = form_data.get("close_timestamp")
    mileage = int(form_data.get("mileage", 0))
    mileage_price = int(form_data.get("mileage_price")) if form_data.get("mileage_price") else None
    rarity = form_data.get("rarity")
    size = form_data.get("size")
    category_id = int(form_data.get("category_id"))

    if id:
        product = db.query(Product).filter(Product.id == id).first()
        # 기존 fungible_items와 fungible_asset_values 삭제
        db.query(FungibleItemProduct).filter(FungibleItemProduct.product_id == id).delete()
        db.query(FungibleAssetProduct).filter(FungibleAssetProduct.product_id == id).delete()
    else:
        product = Product()
        db.add(product)

    product.name = name
    product.order = order
    product.google_sku = google_sku
    product.apple_sku = apple_sku
    product.apple_sku_k = apple_sku_k
    product.product_type = ProductType(product_type)
    product.required_level = required_level
    product.daily_limit = daily_limit
    product.weekly_limit = weekly_limit
    product.account_limit = account_limit
    product.active = active
    product.discount = discount
    product.open_timestamp = datetime.fromisoformat(open_timestamp.replace('Z', '+00:00')) if open_timestamp else None
    product.close_timestamp = datetime.fromisoformat(close_timestamp.replace('Z', '+00:00')) if close_timestamp else None
    product.mileage = mileage
    product.mileage_price = mileage_price
    product.rarity = ProductRarity(rarity) if rarity else ProductRarity.NORMAL
    product.size = ProductAssetUISize(size) if size else ProductAssetUISize.ONE_BY_ONE

    # 카테고리 설정
    category = db.query(Category).filter(Category.id == category_id).first()
    if category:
        product.category_list = [category]

    # Fungible Items 추가
    for key, value in form_data.items():
        if key.startswith("fungible_items[") and key.endswith("][sheet_item_id]"):
            index = key.split("[")[1].split("]")[0]
            sheet_item_id = int(value)
            fungible_item_id = form_data.get(f"fungible_items[{index}][fungible_item_id]")
            amount = int(form_data.get(f"fungible_items[{index}][amount]"))
            name = form_data.get(f"fungible_items[{index}][name]")

            fungible_item = FungibleItemProduct(
                product_id=product.id,
                sheet_item_id=sheet_item_id,
                fungible_item_id=fungible_item_id,
                amount=amount,
                name=name
            )
            db.add(fungible_item)

    # Fungible Asset Values 추가
    for key, value in form_data.items():
        if key.startswith("fungible_asset_values[") and key.endswith("][ticker]"):
            index = key.split("[")[1].split("]")[0]
            ticker = value
            amount = float(form_data.get(f"fungible_asset_values[{index}][amount]"))

            fungible_asset = FungibleAssetProduct(
                product_id=product.id,
                ticker=ticker,
                amount=amount,
                decimal_places=18,  # 기본값으로 18 설정
            )
            db.add(fungible_asset)

    # 이미지 파일 처리
    if detail_image:
        file_name = product.get_image_name()

        # S3에 업로드
        for folder in S3_IMAGE_DETAIL_FOLDER:
            s3_key = f"{folder}{file_name}"
            try:
                # 파일 내용을 바이트로 읽어서 업로드
                file_content = await detail_image.read()
                s3_client.put_object(
                    Bucket=S3_BUCKET,
                    Key=s3_key,
                    Body=file_content,
                    ContentType=detail_image.content_type
                )
            except Exception as e:
                print(f"Detail 이미지 업로드 실패: {e}")

    if list_image:
        file_name = product.get_image_name()

        # S3에 업로드
        for folder in S3_IMAGE_LIST_FOLDER:
            s3_key = f"{folder}{file_name}"
            try:
                # 파일 내용을 바이트로 읽어서 업로드
                file_content = await list_image.read()
                s3_client.put_object(
                    Bucket=S3_BUCKET,
                    Key=s3_key,
                    Body=file_content,
                    ContentType=list_image.content_type
                )
            except Exception as e:
                print(f"List 이미지 업로드 실패: {e}")

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise e

    # CloudFront 캐시 무효화
    try:
        cloudfront_client.create_invalidation(
            DistributionId=os.getenv("CLOUDFRONT_DISTRIBUTION_1"),
            InvalidationBatch={
                "Paths": {"Quantity": 1, "Items": ["/*"]},
                "CallerReference": str(os.urandom(16))
            }
        )
    except Exception as e:
        print(f"CloudFront 캐시 무효화 실패: {e}")

    return RedirectResponse(url="/products", status_code=303)

# ✅ Product 삭제
@app.get("/products/delete/{id}")
def delete_product(id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == id).first()
    if product:
        db.delete(product)
        db.commit()
    return RedirectResponse(url="/products", status_code=303)

@app.get("/categories")
async def list_categories(request: Request, db: Session = Depends(get_db)):
    categories = db.query(Category).all()
    categories_dict = [category.to_dict() for category in categories]
    return templates.TemplateResponse("categories.html", {"request": request, "categories": categories_dict})

@app.post("/categories/save")
async def save_category(request: Request, db: Session = Depends(get_db)):
    form_data = await request.form()
    category_id = form_data.get("id")

    if category_id:
        category = db.query(Category).filter(Category.id == category_id).first()
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")
    else:
        category = Category()
        db.add(category)

    category.name = form_data.get("name")
    category.order = int(form_data.get("order"))
    category.l10n_key = form_data.get("l10n_key")
    category.active = form_data.get("active") == "on"

    open_timestamp = form_data.get("open_timestamp")
    if open_timestamp:
        category.open_timestamp = datetime.fromisoformat(open_timestamp)
    else:
        category.open_timestamp = None

    close_timestamp = form_data.get("close_timestamp")
    if close_timestamp:
        category.close_timestamp = datetime.fromisoformat(close_timestamp)
    else:
        category.close_timestamp = None

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    return RedirectResponse(url="/categories", status_code=303)

@app.get("/categories/delete/{category_id}")
async def delete_category(category_id: int, db: Session = Depends(get_db)):
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    try:
        db.delete(category)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    return RedirectResponse(url="/categories", status_code=303)

@app.get("/l10n")
async def l10n_page(request: Request):
    return templates.TemplateResponse("upload_l10n.html", {"request": request})

@app.post("/l10n/upload/product")
async def upload_product_l10n(request: Request, file: UploadFile = File(...)):
    try:
        # 임시 파일로 저장
        temp_path = "product.csv"
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # S3에 업로드
        for s3_key in S3_KEYS:
            s3_client.upload_file(temp_path, S3_BUCKET, s3_key)

        # 임시 파일 삭제
        os.remove(temp_path)

        # CloudFront 캐시 무효화
        cache_result = invalidate_cloudfront()

        return templates.TemplateResponse(
            "upload_l10n.html",
            {
                "request": request,
                "message": "Product 번역어 파일이 성공적으로 업로드되었습니다." + (f"CloudFront 캐시 무효화 결과: {cache_result}"),
                "message_type": "success"
            }
        )
    except Exception as e:
        return templates.TemplateResponse(
            "upload_l10n.html",
            {
                "request": request,
                "message": f"업로드 중 오류가 발생했습니다: {str(e)}",
                "message_type": "danger"
            }
        )

@app.post("/l10n/upload/category")
async def upload_category_l10n(request: Request, file: UploadFile = File(...)):
    try:
        # 임시 파일로 저장
        temp_path = "category.csv"
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # S3에 업로드
        # S3에 업로드
        for s3_key in S3_CATEGORY_KEYS:
            s3_client.upload_file(temp_path, S3_BUCKET, s3_key)

        # 임시 파일 삭제
        os.remove(temp_path)

        # CloudFront 캐시 무효화
        cache_result = invalidate_cloudfront()

        return templates.TemplateResponse(
            "upload_l10n.html",
            {
                "request": request,
                "message": "Category 번역어 파일이 성공적으로 업로드되었습니다." + (f"CloudFront 캐시 무효화 결과: {cache_result}"),
                "message_type": "success"
            }
        )
    except Exception as e:
        return templates.TemplateResponse(
            "upload_l10n.html",
            {
                "request": request,
                "message": f"업로드 중 오류가 발생했습니다: {str(e)}",
                "message_type": "danger"
            }
        )

@app.get("/")
async def root():
    return RedirectResponse(url="/products", status_code=303)
