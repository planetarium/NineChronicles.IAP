import aws_cdk as cdk_core
import boto3
from aws_cdk import (
    RemovalPolicy, Stack,
    aws_iam as _iam,
    aws_lambda as _lambda,
    aws_lambda_event_sources as _evt_src,
)
from constructs import Construct

from common import COMMON_LAMBDA_EXCLUDE
from worker import WORKER_LAMBDA_EXCLUDE


class WorkerStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        envs = kwargs.get("env")
        stage = kwargs.pop("stage", "development")
        profile_name = kwargs.pop("profile_name", "default")
        shared_stack = kwargs.pop("shared_stack", None)
        if shared_stack is None:
            raise ValueError("Shared stack not found. Please provide shared stack.")
        super().__init__(scope, construct_id, **kwargs)

        # Lambda Layer
        layer = _lambda.LayerVersion(
            self, f"{stage}-9c-iap-worker-lambda-layer",
            code=_lambda.AssetCode("worker/layer/"),
            description="Lambda layer for 9c IAP Worker",
            compatible_runtimes=[
                _lambda.Runtime.PYTHON_3_10,
            ],
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Lambda Role
        role = _iam.Role(
            self, f"{stage}-9c-iap-worker-role",
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
        # FIXME: Move this to github secrets?
        sess = boto3.Session(region_name=envs.region, profile_name=profile_name)
        ssm = sess.client("ssm")
        resp = ssm.get_parameter(Name=f"{stage}_9c_IAP_KMS_KEY_ID", WithDecryption=True)
        kms_key_id = resp["Parameter"]["Value"]
        role.add_to_policy(
            _iam.PolicyStatement(
                actions=["kms:GetPublicKey"],
                resources=[f"arn:aws:kms:{envs.region}:{envs.account}:key/{kms_key_id}"]
            )
        )
        role.add_to_policy(
            _iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[f"arn:aws:ssm:ap-northeast-2:838612679705:parameter/{stage}_9c_IAP_KMS_KEY_ID"]
            )
        )

        # Environment variables
        # ssm = boto3.client("ssm", region_name="us-east-1")
        # Get env.variables from SSM by stage
        env = {
            "REGION": envs.region,
            "ENV": stage,
            "SECRET_ARN": shared_stack.rds.secret.secret_arn,
            "DB_URI": f"postgresql://"
                      f"{shared_stack.credentials.username}:[DB_PASSWORD]"
                      f"@{shared_stack.rds.db_instance_endpoint_address}"
                      f"/iap",
        }
        # Lambda Function
        exclude_list = [".idea", ".gitignore", ]
        exclude_list.extend(COMMON_LAMBDA_EXCLUDE)
        exclude_list.extend(WORKER_LAMBDA_EXCLUDE)

        function = _lambda.Function(
            self, f"{stage}-9c-iap-worker-function",
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
