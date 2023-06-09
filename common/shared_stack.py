from dataclasses import dataclass
from typing import Dict

from aws_cdk import (
    Stack,
    aws_ec2 as _ec2,
    aws_rds as _rds,
    aws_sqs as _sqs,
)
from constructs import Construct


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
        stage = kwargs.pop("stage", "development")
        resource_data = RESOURCE_DICT.get(stage, None)
        if resource_data is None:
            raise KeyError(f"{stage} is not valid stage. Please select one of {list(RESOURCE_DICT.keys())}")
        super().__init__(scope, construct_id, **kwargs)

        # VPC
        self.vpc = _ec2.Vpc.from_lookup(self, f"{stage}-9c-iap-vpc", vpc_id=resource_data.vpc_id)

        # SQS
        self.dlq = _sqs.Queue(self, f"{stage}-9c-iap-dlq")
        self.q = _sqs.Queue(
            self, f"{stage}-9c-iap-queue",
            dead_letter_queue=_sqs.DeadLetterQueue(max_receive_count=2, queue=self.dlq),
        )

        # RDS
        self.credentials = _rds.Credentials.from_username("iap")
        self.rds = _rds.DatabaseInstance(
            self, f"{stage}-9c-iap-rds",
            engine=_rds.DatabaseInstanceEngine.postgres(version=_rds.PostgresEngineVersion.VER_15_2),
            vpc=self.vpc,
            vpc_subnets=_ec2.SubnetSelection(subnet_type=_ec2.SubnetType.PRIVATE_ISOLATED),
            database_name="iap",
            credentials=self.credentials,
            instance_type=_ec2.InstanceType.of(_ec2.InstanceClass.BURSTABLE4_GRAVITON, _ec2.InstanceSize.MICRO),
        )
