#!/usr/bin/env python3
import os

import aws_cdk as cdk
from dotenv import dotenv_values

from common import logger, Config
from common.shared_stack import SharedStack
from iap.iap_cdk_stack import APIStack
from worker.worker_cdk_stack import WorkerStack

stage = os.environ.get("STAGE", "development")

if os.path.exists(f".env.{stage}"):
    env_values = dotenv_values(f".env.{stage}")
    if stage != env_values["STAGE"]:
        logger.error(f"Provided stage {stage} is not identical with STAGE in env: {env_values['STAGE']}")
        exit(1)
else:
    env_values = os.environ

print(env_values)

config = Config(**{k.lower(): v for k, v in env_values.items()})
print(config.__dict__)

app = cdk.App()
shared = SharedStack(
    app, f"{config.stage}-9c-iap-SharedStack",
    env=cdk.Environment(
        account=config.account_id, region=config.region,
    ),
    config=config,
)

APIStack(
    app, f"{config.stage}-9c-iap-APIStack",
    env=cdk.Environment(
        account=config.account_id, region=config.region,
    ),
    config=config,
    shared_stack=shared,
)

WorkerStack(
    app, f"{config.stage}-9c-iap-WorkerStack",
    env=cdk.Environment(
        account=config.account_id, region=config.region,
    ),
    config=config,
    shared_stack=shared,
)

app.synth()
