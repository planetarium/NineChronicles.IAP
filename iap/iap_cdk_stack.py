import aws_cdk as cdk_core
from aws_cdk import (
    RemovalPolicy, Stack,
    aws_apigateway as _apig,
    aws_certificatemanager as _acm,
    aws_iam as _iam,
    aws_lambda as _lambda,
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
                    shared_stack.kms_key_id_arn,
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

        # Environment Variables
        env = {
            "REGION_NAME": config.region_name,
            "ENV": config.stage,
            "SECRET_ARN": shared_stack.rds.secret.secret_arn,
            "DB_URI": f"postgresql://"
                      f"{shared_stack.credentials.username}:[DB_PASSWORD]"
                      f"@{shared_stack.rds.db_instance_endpoint_address}"
                      f"/iap",
            "LOGGING_LEVEL": "INFO",
            "DB_ECHO": "False",
            "SQS_URL": shared_stack.q.queue_url,
            "GOOGLE_PACKAGE_NAME": "com.Planetarium.NineChronicles",
            "APPLE_VALIDATION_URL": "",
            "HEADLESS": config.headless,
        }

        # Lambda Function
        exclude_list = [".", "*", ".idea", ".gitignore", ]
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
        )

        # ACM & Custom Domain
        if config.stage != "development":
            certificate = _acm.Certificate.from_certificate_arn(
                self, "9c-acm",
                certificate_arn="arn:aws:acm:us-east-2:319679068466:certificate/2481ac9e-2037-4331-9234-4b3f86d50ad3"
            )
            custom_domain = _apig.DomainNameOptions(
                domain_name=f"{'dev-' if config.stage == 'developmenet' else ''}iap.nine-chronicles.com",
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
            deploy_options=_apig.StageOptions(stage_name=config.stage),
            domain_name=custom_domain,
        )

        # Route53
        if config.stage != "development":
            from aws_cdk import (aws_route53 as _r53, aws_route53_targets as _targets)

            hosted_zone = _r53.PublicHostedZone.from_lookup(self, "9c-hosted-zone", domain_name="nine-chronicles.com")
            record = _r53.ARecord(
                self, f"{config.stage}-9c-iap-record", zone=hosted_zone,
                target=_r53.RecordTarget.from_alias(_targets.ApiGateway(apig))
            )
