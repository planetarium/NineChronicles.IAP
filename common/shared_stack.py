import os
from dataclasses import dataclass
from shutil import copyfile
from typing import Dict

import boto3
from aws_cdk import (
    Stack,
    aws_ec2 as _ec2,
    aws_rds as _rds,
    aws_sqs as _sqs,
)
from constructs import Construct

from common import logger, Config
from common.utils import fetch_parameter, fetch_secrets


@dataclass
class ResourceDict:
    vpc_id: str


RESOURCE_DICT: Dict[str, ResourceDict] = {
    "development": ResourceDict(
        vpc_id="vpc-0cf2339a10213911d",  # Test VPC in AWS Dev Account - apne2 region
    ),
    "staging": ResourceDict(
        vpc_id="vpc-08ee9f2dbd1c97ac6",  # Internal VPC
    ),
    "production": ResourceDict(
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
            dead_letter_queue=_sqs.DeadLetterQueue(max_receive_count=2, queue=self.dlq),
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
            engine=_rds.DatabaseInstanceEngine.postgres(version=_rds.PostgresEngineVersion.VER_15_2),
            vpc=self.vpc,
            vpc_subnets=_ec2.SubnetSelection(subnet_type=_ec2.SubnetType.PRIVATE_ISOLATED),
            database_name="iap",
            credentials=self.credentials,
            instance_type=_ec2.InstanceType.of(_ec2.InstanceClass.BURSTABLE4_GRAVITON, _ec2.InstanceSize.MICRO),
            security_groups=[self.rds_security_group]
        )

        # SecureStrings in Parameter Store
        PARAMETER_LIST = (
            ("KMS_KEY_ID", True),
            ("GOOGLE_CREDENTIAL", True),
        )
        ssm = boto3.client("ssm", region_name=config.region_name,
                           aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
                           aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY")
                           )

        for param, secure in PARAMETER_LIST:
            try:
                param_value = fetch_parameter(config.region, f"{config.stage}_9c_IAP_{param}", secure)
                logger.debug(param_value["Value"])
                logger.info(f"{param} has already been set.")
            except ssm.exceptions.ParameterNotFound:
                try:
                    ssm.put_parameter(
                        Name=f"{config.stage}_9c_IAP_{param}",
                        Value=getattr(config, param.lower()),
                        Type="SecureString" if secure else "String",
                        Overwrite=False
                    )
                    logger.info(f"{config.stage}_9c_IAP_{param} has been set")
                    param_value = fetch_parameter(config.region, f"{config.stage}_9c_IAP_{param}", secure)
                except Exception as e:
                    logger.error(e)

            else:
                setattr(self, f"{param.lower()}_arn", param_value["ARN"])

        # alembic
        db_password = fetch_secrets(config.region, self.rds.secret.secret_arn)["password"]
        copyfile("alembic.ini.example", "alembic.ini")
        with open("alembic.ini", "a") as f:
            f.writelines([
                f"[{config.stage}]",
                f"postgresql://"
                f"{self.credentials.username}:{db_password}"
                f"@{self.rds.db_instance_endpoint_address}"
                f"/iap"
            ])
