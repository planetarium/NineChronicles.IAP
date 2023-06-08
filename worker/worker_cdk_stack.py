import aws_cdk as cdk_core
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
        stage = kwargs.pop("stage", "development")
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

        # Environment variables
        # ssm = boto3.client("ssm", region_name="us-east-1")
        # Get env.variables from SSM by stage
        env = {
            "ENV": stage,
            "DB_URI": f"{shared_stack.credentials.username}:{shared_stack.credentials.password}@{shared_stack.rds.instance_endpoint}/iap",
        }
        # Lambda Function
        exclude_list = [".", "*", ".idea", ".gitignore", ]
        exclude_list.extend(COMMON_LAMBDA_EXCLUDE)
        exclude_list.extend(WORKER_LAMBDA_EXCLUDE)

        function = _lambda.Function(
            self, f"{stage}-9c-iap-worker-function",
            runtime=_lambda.Runtime.PYTHON_3_10,
            description="9c Action making worker of NineChronicles.IAP",
            code=_lambda.AssetCode(".", exclude=exclude_list),
            handler="worker.handler.handle",
            layers=[layer],
            role=role,
            vpc=shared_stack.vpc,
            timeout=cdk_core.Duration.seconds(30),
            environment=env,
            events=[
                _evt_src.SqsEventSource(shared_stack.q)
            ]
        )
