import os
from dataclasses import dataclass
from typing import Dict

import aws_cdk as cdk_core
import boto3
from aws_cdk import (
    Stack,
    aws_ec2 as _ec2,
    aws_rds as _rds,
    aws_sqs as _sqs,
)
from constructs import Construct

from common import Config, logger
from common.utils.aws import fetch_parameter


@dataclass
class ResourceDict:
    vpc_id: str


RESOURCE_DICT: Dict[str, ResourceDict] = {
    "development": ResourceDict(
        vpc_id="vpc-0cf2339a10213911d",  # Test VPC in AWS Dev Account - apne2 region
    ),
    "internal": ResourceDict(
        vpc_id="vpc-08ee9f2dbd1c97ac6",  # Internal VPC
    ),
    "preview": ResourceDict(
        vpc_id="vpc-08ee9f2dbd1c97ac6",  # Internal VPC
    ),
    "mainnet": ResourceDict(
        vpc_id="vpc-01a0ef2aa2c41bb26",  # Main VPC
    ),
}


class SharedStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        config: Config = kwargs.pop("config")
        resource_data = RESOURCE_DICT.get(config.stage, None)
        if resource_data is None:
            raise KeyError(f"{config.stage} is not valid stage. Please select one of {list(RESOURCE_DICT.keys())}")
        super().__init__(scope, construct_id, **kwargs)

        # VPC
        self.vpc = _ec2.Vpc.from_lookup(self, f"{config.stage}-9c-iap-vpc", vpc_id=resource_data.vpc_id)

        # SQS
        self.dlq = _sqs.Queue(self, f"{config.stage}-9c-iap-dlq")
        self.q = _sqs.Queue(
            self, f"{config.stage}-9c-iap-queue",
            dead_letter_queue=_sqs.DeadLetterQueue(max_receive_count=15, queue=self.dlq),
            visibility_timeout=cdk_core.Duration.seconds(20),
        )

        self.voucher_dlq = _sqs.Queue(self, f"{config.stage}-9c-iap-voucher-dlq")
        self.voucher_q = _sqs.Queue(
            self, f"{config.stage}-9c-iap-voucher-queue",
            dead_letter_queue=_sqs.DeadLetterQueue(max_receive_count=10, queue=self.voucher_dlq),
            visibility_timeout=cdk_core.Duration.seconds(30),
        )

        # RDS
        self.rds_security_group = _ec2.SecurityGroup(
            self, f"{config.stage}-9c-iap-rds-sg", vpc=self.vpc, allow_all_outbound=True
        )
        self.rds_security_group.add_ingress_rule(
            peer=_ec2.Peer.ipv4("0.0.0.0/0"),
            connection=_ec2.Port.tcp(5432),
            description="Allow PSQL from outside",
        )
        self.rds_security_group.add_ingress_rule(
            peer=self.rds_security_group,
            connection=_ec2.Port.tcp(5432),
            description="Allow PSQL from outside",
        )
        self.credentials = _rds.Credentials.from_username("iap")
        self.rds = _rds.DatabaseInstance(
            self, f"{config.stage}-9c-iap-rds",
            instance_identifier=f"{config.stage}-9c-iap-rds",
            engine=_rds.DatabaseInstanceEngine.postgres(version=_rds.PostgresEngineVersion.VER_15_7),
            vpc=self.vpc,
            vpc_subnets=_ec2.SubnetSelection(),
            database_name="iap",
            credentials=self.credentials,
            instance_type=(
                _ec2.InstanceType.of(_ec2.InstanceClass.M6G, _ec2.InstanceSize.LARGE)
                if config.stage == "mainnet" else
                _ec2.InstanceType.of(_ec2.InstanceClass.BURSTABLE4_GRAVITON, _ec2.InstanceSize.MICRO)
            ),
            security_groups=[self.rds_security_group],
        )

        # SecureStrings in Parameter Store
        PARAMETER_LIST = (
            ("KMS_KEY_ID", True),
            ("ADHOC_KMS_KEY_ID", True),
            ("GOOGLE_CREDENTIAL", True),
            ("APPLE_CREDENTIAL", True),
            ("SEASON_PASS_JWT_SECRET", True),
            ("VOUCHER_JWT_SECRET", True),
            ("HEADLESS_GQL_JWT_SECRET", True),
            ("JWT_SECRET", True),
        )
        ssm = boto3.client("ssm", region_name=config.region_name,
                           aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
                           aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY")
                           )

        param_value_dict = {}
        for param, secure in PARAMETER_LIST:
            param_value_dict[param] = None
            try:
                prev_param = ssm.get_parameter(Name=f"{config.stage}_9c_IAP_{param}", WithDecryption=secure)["Parameter"]
                logger.debug(prev_param["Value"])
                if prev_param["Value"] != getattr(config, param.lower()):
                    logger.info(f"The value of {param} has been changed. Update to new value...")
                    raise ValueError("Update to new value")
                else:
                    param_value_dict[param] = prev_param
                    logger.info(f"{param} has already been set.")
            except (ssm.exceptions.ParameterNotFound, ValueError):
                try:
                    ssm.put_parameter(
                        Name=f"{config.stage}_9c_IAP_{param}",
                        Value=getattr(config, param.lower()),
                        Type="SecureString" if secure else "String",
                        Overwrite=True
                    )
                    logger.info(f"{config.stage}_9c_IAP_{param} has been set")
                    param_value_dict[param] = fetch_parameter(
                        config.region_name, f"{config.stage}_9c_IAP_{param}", secure
                    )
                except Exception as e:
                    logger.error(e)
                    raise e

        for k, v in param_value_dict.items():
            setattr(self, f"{k.lower()}_arn", v["ARN"])
