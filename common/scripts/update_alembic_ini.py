import os
from shutil import copyfile

import boto3

from common.utils import fetch_secrets


def update_alembic_ini():
    stage = os.environ.get("STAGE", "development")
    sess = boto3.session.Session(
        region_name=os.environ.get("REGION_NAME"),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    )
    client = sess.client("rds")
    rds = client.describe_db_instances(DBInstanceIdentifier=f"{stage}-9c-iap-rds")
    if not len(rds["DBInstances"]):
        raise Exception(f"{stage}-9c-iap-rds DB Not Found")

    db = rds[0]
    secret_arn = db["MasterUserSecret"]["SecretArn"]
    db_password = fetch_secrets(os.environ.get("REGION_NAME"), secret_arn)["password"]
    copyfile("alembic.ini.example", "alembic.ini")
    with open("alembic.ini", "a") as f:
        f.writelines([
            f"[{stage}]",
            f"postgresql://"
            f"{db['MasterUsername']}:{db_password}"
            f"@{db['Endpoint']['Address']}"
            f"/iap"
        ])


if __name__ == "__main__":
    update_alembic_ini()
