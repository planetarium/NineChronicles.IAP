import os

import aws_cdk as cdk_core
import boto3
from aws_cdk import (
    RemovalPolicy, Stack,
    aws_iam as _iam,
    aws_lambda as _lambda,
    aws_lambda_event_sources as _evt_src,
    aws_events as _events,
    aws_events_targets as _event_targets,
)
from constructs import Construct

from common import COMMON_LAMBDA_EXCLUDE, Config
from worker import WORKER_LAMBDA_EXCLUDE


class WorkerStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        config: Config = kwargs.pop("config")
        shared_stack = kwargs.pop("shared_stack", None)
        if shared_stack is None:
            raise ValueError("Shared stack not found. Please provide shared stack.")
        super().__init__(scope, construct_id, **kwargs)

        # Lambda Layer
        layer = _lambda.LayerVersion(
            self, f"{config.stage}-9c-iap-worker-lambda-layer",
            code=_lambda.AssetCode("worker/layer/"),
            description="Lambda layer for 9c IAP Worker",
            compatible_runtimes=[
                _lambda.Runtime.PYTHON_3_10,
            ],
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Lambda Role
        role = _iam.Role(
            self, f"{config.stage}-9c-iap-worker-role",
            assumed_by=_iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                _iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaVPCAccessExecutionRole"),
            ]
        )
        # DB Password
        role.add_to_policy(
            _iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[shared_stack.rds.secret.secret_arn],
            )
        )
        # KMS
        ssm = boto3.client("ssm", region_name=config.region_name,
                           aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
                           aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
                           )
        resp = ssm.get_parameter(Name=f"{config.stage}_9c_IAP_KMS_KEY_ID", WithDecryption=True)
        kms_key_id = resp["Parameter"]["Value"]
        role.add_to_policy(
            _iam.PolicyStatement(
                actions=["kms:GetPublicKey", "kms:Sign"],
                resources=[f"arn:aws:kms:{config.region_name}:{config.account_id}:key/{kms_key_id}"]
            )
        )
        role.add_to_policy(
            _iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[
                    shared_stack.google_credential_arn,
                    shared_stack.kms_key_id_arn,
                ]
            )
        )

        # Environment variables
        # ssm = boto3.client("ssm", region_name="us-east-1")
        # Get env.variables from SSM by stage
        env = {
            "REGION_NAME": config.region_name,
            "ENV": config.stage,
            "SECRET_ARN": shared_stack.rds.secret.secret_arn,
            "DB_URI": f"postgresql://"
                      f"{shared_stack.credentials.username}:[DB_PASSWORD]"
                      f"@{shared_stack.rds.db_instance_endpoint_address}"
                      f"/iap",
            "GOOGLE_PACKAGE_NAME": "com.Planetarium.NineChronicles",
            "HEADLESS": config.headless,
        }

        # Worker Lambda Function
        exclude_list = [".idea", ".gitignore", ]
        exclude_list.extend(COMMON_LAMBDA_EXCLUDE)
        exclude_list.extend(WORKER_LAMBDA_EXCLUDE)

        worker = _lambda.Function(
            self, f"{config.stage}-9c-iap-worker-function",
            runtime=_lambda.Runtime.PYTHON_3_10,
            description="9c Action making worker of NineChronicles.IAP",
            code=_lambda.AssetCode("worker/worker/", exclude=exclude_list),
            handler="handler.handle",
            layers=[layer],
            role=role,
            vpc=shared_stack.vpc,
            timeout=cdk_core.Duration.seconds(30),
            environment=env,
            events=[
                _evt_src.SqsEventSource(shared_stack.q)
            ]
        )

        # Tracker Lambda Function
        tracker = _lambda.Function(
            self, f"{config.stage}-9c-iap-tracker-function",
            runtime=_lambda.Runtime.PYTHON_3_10,
            description="9c transaction status tracker of NineChronicles.IAP",
            code=_lambda.AssetCode("worker/worker/", exclude=exclude_list),
            handler="tracker.track_tx",
            layers=[layer],
            role=role,
            vpc=shared_stack.vpc,
            timeout=cdk_core.Duration.seconds(50),
            environment=env,
        )

        # Every minute
        minute_event_rule = _events.Rule(
            self, f"{config.stage}-9c-iap-tracker-event",
            schedule=_events.Schedule.cron(minute="*")  # Every minute
        )
        minute_event_rule.add_target(_event_targets.LambdaFunction(tracker))

        # Price updater Lambda function
        updater = _lambda.Function(
            self, f"{config.stage}-9c-iap-price-updater-function",
            runtime=_lambda.Runtime.PYTHON_3_10,
            description="9c IAP price updater from google/apple store",
            code=_lambda.AssetCode("worker/worker", exclude=exclude_list),
            handler="updater.update_prices",
            layers=[layer],
            role=role,
            vpc=shared_stack.vpc,
            timeout=cdk_core.Duration.seconds(60),
            environment=env,
        )

        # Every hour
        hourly_event_rule = _events.Rule(
            self, f"{config.stage}-9c-iap-price-updater-event",
            schedule=_events.Schedule.cron(minute="0")  # Every hour
        )

        hourly_event_rule.add_target(_event_targets.LambdaFunction(updater))
