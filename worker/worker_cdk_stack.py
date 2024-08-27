import os
from copy import deepcopy

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
        resp = ssm.get_parameter(Name=f"{config.stage}_9c_IAP_ADHOC_KMS_KEY_ID", WithDecryption=True)
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
                    shared_stack.apple_credential_arn,
                    shared_stack.kms_key_id_arn,
                    shared_stack.adhoc_kms_key_id_arn,
                    shared_stack.voucher_jwt_secret_arn,
                    shared_stack.headless_gql_jwt_secret_arn,
                ]
            )
        )

        # Environment variables
        # ssm = boto3.client("ssm", region_name="us-east-1")
        # Get env.variables from SSM by stage
        env = {
            "REGION_NAME": config.region_name,
            "STAGE": config.stage,
            "SECRET_ARN": shared_stack.rds.secret.secret_arn,
            "DB_URI": f"postgresql://"
                      f"{shared_stack.credentials.username}:[DB_PASSWORD]"
                      f"@{shared_stack.rds.db_instance_endpoint_address}"
                      f"/iap",
            "GOOGLE_PACKAGE_NAME": config.google_package_name,
            "HEADLESS": config.headless,
            "ODIN_GQL_URL": config.odin_gql_url,
            "HEIMDALL_GQL_URL": config.heimdall_gql_url,
            "PLANET_URL": config.planet_url,
            "BRIDGE_DATA": config.bridge_data,
            "HEADLESS_GQL_JWT_SECRET": config.headless_gql_jwt_secret,
        }

        # Cloudwatch Events
        ## Every minute
        minute_event_rule = _events.Rule(
            self, f"{config.stage}-9c-iap-every-minute-event",
            schedule=_events.Schedule.cron(minute="*")  # Every minute
        )
        # Every ten minute
        ten_minute_event_rule = _events.Rule(
            self, f"{config.stage}-9c-iap-ten-minute-event",
            schedule=_events.Schedule.cron(minute="*/10")  # Every ten minute
        )
        ## Every hour
        hourly_event_rule = _events.Rule(
            self, f"{config.stage}-9c-iap-hourly-event",
            schedule=_events.Schedule.cron(minute="0")  # Every hour
        )
        # Everyday 01:00 UTC
        everyday_0100_rule = _events.Rule(
            self, f"{config.stage}-9c-iap-everyday-0100-event",
            schedule=_events.Schedule.cron(minute="0", hour="1")  # Every day 01:00 UTC
        )

        # Worker Lambda Function
        exclude_list = [".idea", ".gitignore", ]
        exclude_list.extend(COMMON_LAMBDA_EXCLUDE)
        exclude_list.extend(WORKER_LAMBDA_EXCLUDE)

        worker = _lambda.Function(
            self, f"{config.stage}-9c-iap-worker-function",
            function_name=f"{config.stage}-9c-iap-worker",
            runtime=_lambda.Runtime.PYTHON_3_10,
            description="9c Action making worker of NineChronicles.IAP",
            code=_lambda.AssetCode("worker/worker/", exclude=exclude_list),
            handler="handler.handle",
            layers=[layer],
            role=role,
            vpc=shared_stack.vpc,
            timeout=cdk_core.Duration.seconds(15),
            environment=env,
            events=[
                _evt_src.SqsEventSource(shared_stack.q)
            ],
            memory_size=1024,
            reserved_concurrent_executions=1,
        )

        # Tracker Lambda Function
        tracker = _lambda.Function(
            self, f"{config.stage}-9c-iap-tracker-function",
            function_name=f"{config.stage}-9c-iap-tx-tracker",
            runtime=_lambda.Runtime.PYTHON_3_10,
            description="9c transaction status tracker of NineChronicles.IAP",
            code=_lambda.AssetCode("worker/worker/", exclude=exclude_list),
            handler="tracker.track_tx",
            layers=[layer],
            role=role,
            vpc=shared_stack.vpc,
            memory_size=1024 if config.stage == "mainnet" else 256,
            timeout=cdk_core.Duration.seconds(50),
            environment=env,
        )
        minute_event_rule.add_target(_event_targets.LambdaFunction(tracker))

        # IAP Status Monitor
        monitor_env = deepcopy(env)
        monitor_env["IAP_GARAGE_WEBHOOK_URL"] = config.iap_garage_webhook_url
        monitor_env["IAP_ALERT_WEBHOOK_URL"] = config.iap_alert_webhook_url
        status_monitor = _lambda.Function(
            self, f"{config.stage}-9c-iap-status-monitor-function",
            function_name=f"{config.stage}-9c-iap-status-monitor",
            description="Receipt and Tx. status monitor for Nine Chronicles",
            runtime=_lambda.Runtime.PYTHON_3_10,
            code=_lambda.AssetCode("worker/worker", exclude=exclude_list),
            handler="status_monitor.handle",
            environment=monitor_env,
            layers=[layer],
            role=role,
            vpc=shared_stack.vpc,
            timeout=cdk_core.Duration.seconds(300),
            memory_size=512,
        )

        if config.stage == "mainnet":
            ten_minute_event_rule.add_target(_event_targets.LambdaFunction(status_monitor))
        # If you want to test monitor in internal, uncomment following statement
        else:
            hourly_event_rule.add_target(_event_targets.LambdaFunction(status_monitor))

        # IAP Voucher
        voucher_env = deepcopy(env)
        voucher_env["VOUCHER_URL"] = config.voucher_url
        voucher_handler = _lambda.Function(
            self, f"{config.stage}-9c-iap-voucher-handler-function",
            function_name=f"{config.stage}-9c-iap-voucher-handler",
            description="IAP voucher handler between IAP and portal",
            runtime=_lambda.Runtime.PYTHON_3_10,
            code=_lambda.AssetCode("worker/worker", exclude=exclude_list),
            handler="voucher.handle",
            layers=[layer],
            environment=voucher_env,
            role=role,
            vpc=shared_stack.vpc,
            timeout=cdk_core.Duration.seconds(30),
            memory_size=512,
            events=[
                _evt_src.SqsEventSource(shared_stack.voucher_q)
            ],
        )

        # Update refund sheet
        refund_env = deepcopy(env)
        refund_env["REFUND_SHEET_ID"] = os.environ.get("REFUND_SHEET_ID")
        google_refund_handler = _lambda.Function(
            self, f"{config.stage}-9c-iap-refund-update-function",
            function_name=f"{config.stage}-9c-iap-refund-update",
            description="Refund google sheet update function",
            runtime=_lambda.Runtime.PYTHON_3_10,
            code=_lambda.AssetCode("worker/worker", exclude=exclude_list),
            handler="google_refund_tracker.handle",
            memory_size=256,
            timeout=cdk_core.Duration.seconds(120),
            role=role,
            environment=refund_env,
            layers=[layer],
            vpc=shared_stack.vpc,
        )
        everyday_0100_rule.add_target(_event_targets.LambdaFunction(google_refund_handler))

        # Event finished
        # # Golden dust by NCG handler
        # env["GOLDEN_DUST_REQUEST_SHEET_ID"] = config.golden_dust_request_sheet_id
        # env["GOLDEN_DUST_WORK_SHEET_ID"] = config.golden_dust_work_sheet_id
        # env["FORM_SHEET"] = config.form_sheet
        # gd_handler = _lambda.Function(
        #     self, f"{config.stage}-9c-iap-goldendust-handler-function",
        #     function_name=f"{config.stage}-9c-iap-goldendust-handler",
        #     runtime=_lambda.Runtime.PYTHON_3_10,
        #     description="Request handler for Golden dust by NCG for PC users",
        #     code=_lambda.AssetCode("worker/worker", exclude=exclude_list),
        #     handler="golden_dust_by_ncg.handle_request",
        #     layers=[layer],
        #     role=role,
        #     vpc=shared_stack.vpc,
        #     timeout=cdk_core.Duration.minutes(8),
        #     environment=env,
        #     memory_size=512,
        #     reserved_concurrent_executions=1,
        # )
        # ten_minute_event_rule.add_target(_event_targets.LambdaFunction(gd_handler))
        #
        # # Golden dust unload Tx. tracker
        # gd_tracker = _lambda.Function(
        #     self, f"{config.stage}-9c-iap-goldendust-tracker-function",
        #     function_name=f"{config.stage}-9c-iap-goldendust-tracker",
        #     runtime=_lambda.Runtime.PYTHON_3_10,
        #     description=f"Tx. status tracker for golden dust unload for PC users",
        #     code=_lambda.AssetCode("worker/worker", exclude=exclude_list),
        #     handler="golden_dust_by_ncg.track_tx",
        #     layers=[layer],
        #     role=role,
        #     vpc=shared_stack.vpc,
        #     timeout=cdk_core.Duration.seconds(50),
        #     environment=env,
        #     memory_size=256,
        # )
        # minute_event_rule.add_target(_event_targets.LambdaFunction(gd_tracker))

        # Manual unload function
        # This function does not have trigger. Go to AWS console and run manually.
        if config.stage != "mainnet":
            manual_unload = _lambda.Function(
                self, f"{config.stage}-9c-iap-manual-unload-function",
                function_name=f"{config.stage}-9c-iap-manual-unload",
                runtime=_lambda.Runtime.PYTHON_3_10,
                description=f"Manual unload Tx. executor from NineChronicles.IAP",
                code=_lambda.AssetCode("worker/worker", exclude=exclude_list),
                handler="manual.handle",
                layers=[layer],
                role=role,
                vpc=shared_stack.vpc,
                timeout=cdk_core.Duration.seconds(300),  # 5min
                environment=env,
                memory_size=512,
            )

            token_issuer = _lambda.Function(
                self, f"{config.stage}-9c-iap-token-issue-function",
                function_name=f"{config.stage}-9c-iap-issue-token",
                runtime=_lambda.Runtime.PYTHON_3_10,
                description=f"Execute IssueTokensFromGarage action",
                code=_lambda.AssetCode("worker/worker", exclude=exclude_list),
                handler="issue_tokens.issue",
                layers=[layer],
                role=role,
                vpc=shared_stack.vpc,
                timeout=cdk_core.Duration.seconds(300),  # 5min
                environment=env,
                memory_size=256,
            )

            asset_transporter = _lambda.Function(
                self, f"{config.stage}-9c-iap-assets-transfer-function",
                function_name=f"{config.stage}-9c-iap-transfer-assets",
                runtime=_lambda.Runtime.PYTHON_3_10,
                description=f"Execute TransferAssets action",
                code=_lambda.AssetCode("worker/worker", exclude=exclude_list),
                handler="manual.transfer_assets.transfer",
                layers=[layer],
                role=role,
                vpc=shared_stack.vpc,
                timeout=cdk_core.Duration.seconds(300),  # 5min
                environment=env,
                memory_size=256,
            )

            lambda_warmer = _lambda.Function(
                self, f"{config.stage}-9c-iap-lambda-warmer",
                function_name=f"{config.stage}-9c-iap-lambda-warmer",
                runtime=_lambda.Runtime.PYTHON_3_10,
                description=f"Warm lambda instance to response fast",
                code=_lambda.AssetCode("worker/worker", exclude=exclude_list),
                handler="lambda_warmer.heat",
                layers=[layer],
                role=role,
                vpc=shared_stack.vpc,
                timeout=cdk_core.Duration.seconds(10),
                environment=env,
                memory_size=128,
            )
            minute_event_rule.add_target(_event_targets.LambdaFunction(lambda_warmer))
