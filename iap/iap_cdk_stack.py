import aws_cdk as cdk_core
import boto3
from aws_cdk import (
    RemovalPolicy, Stack,
    aws_apigateway as _apig,
    aws_certificatemanager as _acm,
    aws_iam as _iam,
    aws_lambda as _lambda,
)
from constructs import Construct

from common import COMMON_LAMBDA_EXCLUDE
from iap import IAP_LAMBDA_EXCLUDE


class APIStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        stage = kwargs.pop("stage", "development")
        shared_stack = kwargs.pop("shared_stack", None)
        if shared_stack is None:
            raise ValueError("Shared stack not found. Please provide shared stack.")
        super().__init__(scope, construct_id, **kwargs)

        # Lambda Layer
        layer = _lambda.LayerVersion(
            self, f"{stage}-9c-iap-api-lambda-layer",
            code=_lambda.AssetCode("iap/layer/"),
            description="Lambda layer for 9c IAP API Service",
            compatible_runtimes=[
                _lambda.Runtime.PYTHON_3_10,
            ],
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Lambda Role
        role = _iam.Role(
            self, f"{stage}-9c-iap-api-role",
            assumed_by=_iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                _iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaVPCAccessExecutionRole"),
            ]
        )

        # Environment Variables
        ssm = boto3.client("ssm", region_name="us-east-2")
        # Get env. variables from SSM by stage
        env = {
            "ENV": stage,
            "DB_URI": f"{shared_stack.credentials.username}:{shared_stack.credentials.password}@{shared_stack.rds.instance_endpoint}/iap",
        }

        # Lambda Function
        exclude_list = [".", "*", ".idea", ".gitignore", ]
        exclude_list.extend(COMMON_LAMBDA_EXCLUDE)
        exclude_list.extend(IAP_LAMBDA_EXCLUDE)

        function = _lambda.Function(
            self, f"{stage}-9c-iap-api-function",
            runtime=_lambda.Runtime.PYTHON_3_10,
            function_name=f"{stage}-9c_iap_api",
            description="HTTP API/Backoffice service of NineChronicles.IAP",
            code=_lambda.AssetCode(".", exclude=exclude_list),
            handler="iap.main.handler",
            layers=[layer],
            role=role,
            vpc=shared_stack.vpc,
            allow_public_subnet=True,
            timeout=cdk_core.Duration.seconds(10),
            environment=env,
        )

        # ACM & Custom Domain
        if stage != "development":
            certificate = _acm.Certificate.from_certificate_arn(
                self, "9c-acm",
                certificate_arn="arn:aws:acm:us-east-2:319679068466:certificate/2481ac9e-2037-4331-9234-4b3f86d50ad3"
            )
            custom_domain = _apig.DomainNameOptions(
                domain_name=f"{'dev-' if stage == 'developmenet' else ''}iap.nine-chronicles.com",
                certificate=certificate,
                security_policy=_apig.SecurityPolicy.TLS_1_2,
                endpoint_type=_apig.EndpointType.EDGE,
            )

        else:
            custom_domain = None

        # API Gateway
        apig = _apig.LambdaRestApi(
            self, f"{stage}-9c_iap-api-apig",
            handler=function,
            deploy_options=_apig.StageOptions(stage_name=stage),
            domain_name=custom_domain,
        )

        # Route53
        if stage != "development":
            from aws_cdk import (aws_route53 as _r53, aws_route53_targets as _targets)
            hosted_zone = _r53.PublicHostedZone.from_lookup(self, "9c-hosted-zone", domain_name="nine-chronicles.com")
            record = _r53.ARecord(
                self, f"{stage}-9c-iap-record", zone=hosted_zone,
                target=_r53.RecordTarget.from_alias(_targets.ApiGateway(apig))
            )
