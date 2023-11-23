import os

import aws_cdk as cdk_core
import boto3
from aws_cdk import (
    RemovalPolicy, Stack,
    aws_apigateway as _apig,
    aws_certificatemanager as _acm,
    aws_iam as _iam,
    aws_lambda as _lambda,
    aws_logs as _logs,
)
from constructs import Construct

from common import COMMON_LAMBDA_EXCLUDE, Config
from iap import IAP_LAMBDA_EXCLUDE


class APIStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        config: Config = kwargs.pop("config")
        shared_stack = kwargs.pop("shared_stack", None)
        if shared_stack is None:
            raise ValueError("Shared stack not found. Please provide shared stack.")
        super().__init__(scope, construct_id, **kwargs)

        # Lambda Layer
        layer = _lambda.LayerVersion(
            self, f"{config.stage}-9c-iap-api-lambda-layer",
            code=_lambda.AssetCode("iap/layer/"),
            description="Lambda layer for 9c IAP API Service",
            compatible_runtimes=[
                _lambda.Runtime.PYTHON_3_10,
            ],
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Lambda Role
        role = _iam.Role(
            self, f"{config.stage}-9c-iap-api-role",
            assumed_by=_iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                _iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaVPCAccessExecutionRole"),
            ],
        )
        role.add_to_policy(
            _iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[
                    shared_stack.google_credential_arn,
                    shared_stack.apple_credential_arn,
                    shared_stack.kms_key_id_arn,
                    shared_stack.season_pass_jwt_secret_arn,
                    f"arn:aws:ssm:{config.region_name}:{config.account_id}:parameter/{config.stage}_9c_SEASON_PASS_HOST"
                ]
            )
        )
        role.add_to_policy(
            _iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[shared_stack.rds.secret.secret_arn],
            )
        )
        role.add_to_policy(
            _iam.PolicyStatement(
                actions=["sqs:sendmessage"],
                resources=[shared_stack.q.queue_arn]
            )
        )
        ssm = boto3.client("ssm", region_name=config.region_name,
                           aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
                           aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
                           )
        resp = ssm.get_parameter(Name=f"{config.stage}_9c_IAP_KMS_KEY_ID", WithDecryption=True)
        kms_key_id = resp["Parameter"]["Value"]
        role.add_to_policy(
            _iam.PolicyStatement(
                actions=["kms:GetPublicKey"],
                resources=[f"arn:aws:kms:{config.region_name}:{config.account_id}:key/{kms_key_id}"]
            )
        )

        # Environment Variables
        env = {
            "REGION_NAME": config.region_name,
            "STAGE": config.stage,
            "SECRET_ARN": shared_stack.rds.secret.secret_arn,
            "DB_URI": f"postgresql://"
                      f"{shared_stack.credentials.username}:[DB_PASSWORD]"
                      f"@{shared_stack.rds.db_instance_endpoint_address}"
                      f"/iap",
            "LOGGING_LEVEL": "INFO",
            "DB_ECHO": "False",
            "SQS_URL": shared_stack.q.queue_url,
            "GOOGLE_PACKAGE_NAME": config.google_package_name,
            "APPLE_BUNDLE_ID": config.apple_bundle_id,
            "APPLE_VALIDATION_URL": config.apple_validation_url,
            "APPLE_KEY_ID": config.apple_key_id,
            "APPLE_ISSUER_ID": config.apple_issuer_id,
            "HEADLESS": config.headless,
            "CDN_HOST": config.cdn_host,
            "PLANET_URL": config.planet_url,
            "BRIDGE_DATA": config.bridge_data,
        }

        # Lambda Function
        exclude_list = [".", "*", ".idea", ".git", ".pytest_cache", ".gitignore", ".github",]
        exclude_list.extend(COMMON_LAMBDA_EXCLUDE)
        exclude_list.extend(IAP_LAMBDA_EXCLUDE)

        function = _lambda.Function(
            self, f"{config.stage}-9c-iap-api-function",
            runtime=_lambda.Runtime.PYTHON_3_10,
            function_name=f"{config.stage}-9c_iap_api",
            description="HTTP API/Backoffice service of NineChronicles.IAP",
            code=_lambda.AssetCode(".", exclude=exclude_list),
            handler="iap.main.handler",
            layers=[layer],
            role=role,
            vpc=shared_stack.vpc,
            security_groups=[shared_stack.rds_security_group],
            timeout=cdk_core.Duration.seconds(10),
            environment=env,
            memory_size=256,
        )

        # ACM & Custom Domain
        if config.stage != "development":
            certificate = _acm.Certificate.from_certificate_arn(
                self, "9c-acm",
                certificate_arn="arn:aws:acm:us-east-1:319679068466:certificate/8e3f8d11-ead8-4a90-bda0-94a35db71678",
            )
            custom_domain = _apig.DomainNameOptions(
                domain_name=f"iap{'-internal' if config.stage == 'internal' else ''}.9c.gg",
                certificate=certificate,
                security_policy=_apig.SecurityPolicy.TLS_1_2,
                endpoint_type=_apig.EndpointType.EDGE,
            )

        else:
            custom_domain = None

        # API Gateway
        apig = _apig.LambdaRestApi(
            self, f"{config.stage}-9c_iap-api-apig",
            handler=function,
            deploy_options=_apig.StageOptions(
                stage_name=config.stage,
                logging_level=_apig.MethodLoggingLevel.INFO,
                metrics_enabled=True,
                data_trace_enabled=True,
            ),
            domain_name=custom_domain,
        )
