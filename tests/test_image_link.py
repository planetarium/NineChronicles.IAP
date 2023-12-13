import pytest
import requests
from sqlalchemy import select

from common.enums import ProductRarity, ProductAssetUISize
from common.models.product import Product, Category

HOST_DICT = {
    "local": "https://dhyrkl3xgx6tk.cloudfront.net",
    "development": "https://dhyrkl3xgx6tk.cloudfront.net",
    "internal": "https://d12930yiv6x601.cloudfront.net",
    "mainnet": "https://d3q2guojv29gp2.cloudfront.net",
}

LANG_DICT = {
    "English": "EN",
    # "Korean": "KO",
    "Portuguese": "PT",
    "ChineseSimplified": "ZH-CN",
}


@pytest.mark.skip("Need to be fixed")
@pytest.mark.usefixtures("session")
@pytest.mark.parametrize("stage", ["internal", "mainnet"])
def test_category(session, stage):
    host = HOST_DICT[stage]
    category_list = session.scalars(select(Category)).fetchall()
    for category in category_list:
        resp = requests.get(f"{host}/{category.path}")
        if resp.status_code != 200:
            print(f"Category image path {category.path} for category ID {category.id} not found.")


@pytest.mark.skip("Need to be fixed")
@pytest.mark.usefixtures("session")
@pytest.mark.parametrize("stage", ["internal", "mainnet"])
def test_image_list(session, stage):
    host = HOST_DICT[stage]
    product_list = session.scalars(select(Product)).fetchall()
    for product in product_list:
        resp = requests.get(f"{host}/{product.path}")
        if resp.status_code != 200:
            print(f"Product list image path {product.path} for product ID {product.id}:{product.name} not found.")


@pytest.mark.skip("Need to be fixed")
@pytest.mark.parametrize("stage", ["internal", "mainnet"])
def test_image_bg(stage):
    host = HOST_DICT[stage]
    for rarity in ProductRarity:
        for size in (ProductAssetUISize.ONE_BY_ONE, ProductAssetUISize.ONE_BY_TWO):
            target_path = f"shop/images/product/list/bg_{rarity.value}_{size.value}.png"
            resp = requests.get(f"{host}/{target_path}")
            if resp.status_code != 200:
                print(f"BG Image Path {target_path} for Rarity {rarity} && Size {size} not found")


@pytest.mark.skip("Need to be fixed")
@pytest.mark.parametrize("stage", ["internal", "mainnet"])
def test_image_detail(stage):
    host = HOST_DICT[stage]
    product_csv_path = "shop/l10n/product.csv"
    csv_resp = requests.get(f"{host}/{product_csv_path}")
    header, *body = [x.split(",") for x in csv_resp.text.split("\n")]
    data = [dict(zip(header, b)) for b in body]
    for d in data:
        if not d["Key"].endswith("_PATH"):
            continue

        for lang, code in LANG_DICT.items():
            target_path = d[lang]
            assert code in target_path
            resp = requests.get(f"{host}/{target_path}")
            if resp.status_code != 200:
                print(f"Detail image path {target_path} for {d['Key']} not found.")
