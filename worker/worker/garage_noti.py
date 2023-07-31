import os

import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from common import logger
from common.utils.aws import fetch_secrets
from common.utils.garage import get_iap_garage, update_iap_garage

DB_URI = os.environ.get("DB_URI")
db_password = fetch_secrets(os.environ.get("REGION_NAME"), os.environ.get("SECRET_ARN"))["password"]
DB_URI = DB_URI.replace("[DB_PASSWORD]", db_password)

ITEM_WARNING_MULTIPLIER = 1000
ITEM_DANGER_MULTIPLIER = 100
ITEM_DICT = {
    "00dfffe23964af9b284d121dae476571b7836b8d9e2e5f510d92a840fecc64fe": {
        "name": "AP Potion",
        "limit": 40
    },
    "3991e04dd808dc0bc24b21f5adb7bf1997312f8700daf1334bf34936e8a0813a": {
        "name": "Hourglass",
        "limit": 40_000
    },
}
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
    update_iap_garage(sess)
    garage = {x.fungible_id: x.amount if x.amount is not None else 0
              for x in get_iap_garage(sess)}

    state_dict = {}
    blocks = []

    for item_id, count in garage.items():
        block = {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{ITEM_DICT[item_id]['name']} : {count:15,d} 개 남음\t"
                        f"(매진까지 `{count // ITEM_DICT[item_id]['limit']}` 구매)"
            }
        }

        if count <= ITEM_DICT[item_id]["limit"] * ITEM_DANGER_MULTIPLIER:
            state_dict[item_id] = "danger"
            block["text"]["text"] = f"{COLOR_PROFILE['danger']['emoji']} " + block["text"]["text"]
        elif count <= ITEM_DICT[item_id]["limit"] * ITEM_WARNING_MULTIPLIER:
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
    resp = requests.post(os.environ.get("IAP_GARAGE_WEBHOOK_URL"), json=payload)
    logger.debug(f"{resp.status_code} :: {resp.text}")
