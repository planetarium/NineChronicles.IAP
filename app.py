#!/usr/bin/env python3
import os
from dataclasses import dataclass

import aws_cdk as cdk

from common.shared_stack import SharedStack
from iap.iap_cdk_stack import APIStack
from worker.worker_cdk_stack import WorkerStack


@dataclass
class Env:
    stage: str
    account_id: str
    region: str


env = Env(
    stage=os.environ.get("STAGE", "development"),
    account_id=os.environ.get("ACCOUNT_ID", "838612679705"),  # AWS Dev Account
    region=os.environ.get("REGION", "ap-northeast-2"),
)

print(env.__dict__)

app = cdk.App()
shared = SharedStack(
    app, f"{env.stage}-9c-iap-SharedStack",
    env=cdk.Environment(
        account=env.account_id, region=env.region,
    ),
    stage=env.stage,
)

APIStack(
    app, f"{env.stage}-9c-iap-APIStack",
    env=cdk.Environment(
        account=env.account_id, region=env.region,
    ),
    stage=env.stage,
    shared_stack=shared,
)

WorkerStack(
    app, f"{env.stage}-9c-iap-WorkerStack",
    env=cdk.Environment(
        account=env.account_id, region=env.region,
    ),
    stage=env.stage,
    shared_stack=shared,
)

app.synth()
