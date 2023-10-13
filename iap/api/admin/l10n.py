import csv
import os
from io import BytesIO
from time import time

import boto3
from fastapi import APIRouter

from common import logger
from iap.schemas.l10n import CsvSchema

router = APIRouter(
    prefix="/l10n",
    tags=["Admin", "L10N"],
)

sess = boto3.session.Session()
stage = os.environ.get("STAGE", "development")


@router.get("/csv/{filename}")
def category_csv(filename: str):
    s3 = sess.client("s3", region_name=os.environ.get("REGION_NAME"))
    s3.download_file("9c-mobile", f"{stage}/shop/l10n/{filename}.csv", f"/tmp/{filename}.csv")
    data = []
    with open(f"/tmp/{filename}.csv", "r", newline="") as f:
        reader = csv.reader(f)
        for i, r in enumerate(reader):
            data.append(r)
    header, *body = data
    return {"header": header, "body": body}


@router.post("/csv/{filename}")
def save_category_csv(filename: str, csv_data: CsvSchema):
    dist_id = "E2ZCSNXISM2YYO"
    # Create CSV
    data = [",".join(csv_data.header)]
    for b in csv_data.body:
        data.append(",".join(b))
    # Upload to S3
    buffer = BytesIO("\n".join(data).encode())
    (sess.client("s3", region_name=os.environ.get("REGION_NAME"))
     .upload_fileobj(buffer, "9c-mobile", f"{stage}/shop/l10n/{filename}.csv"))
    # Invalidation
    resp = sess.client("cloudfront").create_invalidation(
        DistributionId=dist_id,
        InvalidationBatch={
            "Paths": {"Quantity": 1, "Items": [f"/shop/l10n/{filename}.csv"]},
            "CallerReference": f"9c_iap_{filename}_{time()}"
        }
    )
    print(resp)
    return f"{filename} uploaded :: {resp['Invalidation']['Id']}"
