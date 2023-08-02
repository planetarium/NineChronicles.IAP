import os

import requests
from sqlalchemy import create_engine
from sqlalchemy import select
from sqlalchemy.orm import scoped_session, sessionmaker

from common.models.product import FungibleItemProduct
from common.utils import fetch_secrets, get_iap_garage

DB_URI = os.environ.get("DB_URI")
db_password = fetch_secrets(os.environ.get("REGION_NAME"), os.environ.get("SECRET_ARN"))["password"]
DB_URI = DB_URI.replace("[DB_PASSWORD]", db_password)

ITEM_WARNING_MULTIPLIER = 1000
ITEM_DANGER_MULTIPLIER = 100

COLOR_PROFILE = {
    "danger": {
        "emoji": ":red_circle:",
        "color": "#F04438",
    },
    "warning": {
        "emoji": ":warning:",
        "color": "#F79009",
    },
    "good": {
        "emoji": ":white_check_mark:",
        "color": "#12B76A",
    },
}

engine = create_engine(DB_URI, pool_size=5, max_overflow=5)


def noti(event, context):
    sess = scoped_session(sessionmaker(bind=engine))
    product_list = sess.scalars(select(FungibleItemProduct)).fetchall()
    item_dict = {p.fungible_item_id: {"name": p.name, "limit": 0} for p in product_list}
    for p in product_list:
        item_dict[p.fungible_item_id]["limit"] = max(p.amount, item_dict[p.fungible_item_id]["limit"])
    garage = {x["fungibleItemId"]: x["count"] if x["count"] is not None else 0
              for x in get_iap_garage(sess)}

    state_dict = {}
    blocks = []

    for item_id, count in garage.items():
        block = {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{item_dict[item_id]['name']} : {count:15,d} 개 남음\t"
                        f"(매진까지 `{count // item_dict[item_id]['limit']}` 구매)"
            }
        }

        if count <= item_dict[item_id]["limit"] * ITEM_DANGER_MULTIPLIER:
            state_dict[item_id] = "danger"
            block["text"]["text"] = f"{COLOR_PROFILE['danger']['emoji']} " + block["text"]["text"]
        elif count <= item_dict[item_id]["limit"] * ITEM_WARNING_MULTIPLIER:
            state_dict[item_id] = "warning"
            block["text"]["text"] = f"{COLOR_PROFILE['warning']['emoji']} " + block["text"]["text"]
        else:
            state_dict[item_id] = "good"
            block["text"]["text"] = f"{COLOR_PROFILE['good']['emoji']} " + block["text"]["text"]

        blocks.append(block)

    representative = ("danger" if "danger" in state_dict.values()
                      else ("warning" if "warning" in state_dict.values()
                            else "good")
                      )

    title = [{
        "type": "header",
        "text": {
            "type": "mrkdwn",
            "text": f"{COLOR_PROFILE[representative]['emoji']} [NineChronicles.IAP] Daily IAP Garage Report"
        }
    }]
    if representative == "danger":
        title.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"\n<@U02S8TASTGW> <@U03PRBN1CMB> 재고 확인 및 충전이 필요합니다."
            }
        })

        payload = {
            "blocks": title,
            "attachments": [
                {
                    "color": COLOR_PROFILE[representative]["color"],
                    "blocks": blocks
                }
            ]
        }
        requests.post(os.environ.get("IAP_GARAGE_WEBHOOK_URL"), json=payload)
