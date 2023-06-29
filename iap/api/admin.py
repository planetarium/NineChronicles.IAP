from fastapi import APIRouter, Depends

from common.enums import Store
from common.utils import update_google_price
from iap import settings
from iap.dependencies import session

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
)


@router.post("/update-price")
def update_price(store: Store, sess=Depends(session)):
    updated_product_count, updated_price_count = (0, 0)
    print(settings.GOOGLE_CREDENTIALS)

    if store in (Store.GOOGLE, Store.GOOGLE_TEST):
        updated_product_count, updated_price_count = update_google_price(
            sess, settings.GOOGLE_CREDENTIALS, settings.GOOGLE_PACKAGE_NAME
        )
    elif store in (Store.APPLE, Store.APPLE_TEST):
        pass
    elif store == Store.TEST:
        pass
    else:
        raise ValueError(f"{store.name} is unsupported store.")

    return f"{updated_price_count} prices in {updated_product_count} products are updated."
