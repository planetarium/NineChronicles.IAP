from fastapi import FastAPI, Depends, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from .database import SessionLocal, engine, Base
from common.models.product import Product, Category
from datetime import datetime
from fastapi import HTTPException

app = FastAPI()
templates = Jinja2Templates(directory="backoffice/templates")

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
    return templates.TemplateResponse("products.html", {"request": request, "products": products})

# ✅ Product 추가/수정 처리
@app.post("/products/save")
def save_product(
    id: int = Form(None), name: str = Form(...), order: int = Form(...), google_sku: str = Form(...),
    apple_sku: str = Form(...), product_type: str = Form(...), required_level: int = Form(None),
    daily_limit: int = Form(None), weekly_limit: int = Form(None), account_limit: int = Form(None),
    active: bool = Form(False), discount: float = Form(0.0), open_timestamp: str = Form(None),
    close_timestamp: str = Form(None), mileage: int = Form(0), db: Session = Depends(get_db)
):
    if id:
        product = db.query(Product).filter(Product.id == id).first()
    else:
        product = Product()
        db.add(product)

    product.name = name
    product.order = order
    product.google_sku = google_sku
    product.apple_sku = apple_sku
    product.product_type = product_type
    product.required_level = required_level
    product.daily_limit = daily_limit
    product.weekly_limit = weekly_limit
    product.account_limit = account_limit
    product.active = active
    product.discount = discount
    product.open_timestamp = open_timestamp
    product.close_timestamp = close_timestamp
    product.mileage = mileage

    db.commit()
    return RedirectResponse(url="/products", status_code=303)

# ✅ Product 삭제
@app.get("/products/delete/{id}")
def delete_product(id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == id).first()
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
