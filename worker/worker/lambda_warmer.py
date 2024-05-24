import requests

from common import logger


def heat(event, context):
    timeout = 1
    try:
        resp = requests.get("https://iap-internal.9c.gg/ping?from=warmer", timeout=timeout)
        print(resp.text)
    except requests.exceptions.Timeout:
        logger.error(f"Ping timed out after {timeout} seconds!")
