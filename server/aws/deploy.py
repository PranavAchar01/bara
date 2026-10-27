"""Package and deploy the fit measurement to AWS Lambda (arm64, Graviton) with a function URL.

    uv run --with boto3 python aws/deploy.py            # build + deploy, prints the URL
    uv run --with boto3 python aws/deploy.py --build    # only build aws/dist/fit.zip

Needs AWS credentials in the environment (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
AWS_DEFAULT_REGION). Creates or updates: an IAM role with only the basic Lambda logging policy,
the function `tangible-fit-measure` (python3.12, arm64, 1024 MB, 30 s), a public function URL,
and a reserved concurrency of 5 so a public URL cannot run away with cost.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src" / "bara" / "vision" / "measure.py"
DIST = HERE / "dist"
ZIP = DIST / "fit.zip"
NAME = "tangible-fit-measure"
ROLE = "tangible-fit-measure-role"
PINS = ["opencv-python-headless==5.0.0.93", "numpy==2.2.6"]


def build() -> Path:
    stage = DIST / "stage"
    shutil.rmtree(DIST, ignore_errors=True)
    stage.mkdir(parents=True)
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--quiet",
            "--target",
            str(stage),
            "--python-platform",
            "aarch64-manylinux_2_28",
            "--python-version",
            "3.12",
            "--only-binary",
            ":all:",
            *PINS,
        ],
        check=True,
    )
    shutil.copy(SRC, stage / "measure.py")
    shutil.copy(HERE / "handler.py", stage / "handler.py")
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(stage.rglob("*")):
            rel = p.relative_to(stage)
            if p.is_dir() or {"__pycache__", "tests"} & set(rel.parts) or rel.suffix == ".pyc":
                continue
            z.write(p, rel)
    print(f"built {ZIP} {ZIP.stat().st_size / 1e6:.1f} MB")  # noqa: T201
    return ZIP


def deploy(zip_path: Path) -> str:
    import boto3
    from botocore.exceptions import ClientError

    iam = boto3.client("iam")
    lam = boto3.client("lambda")
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    try:
        role_arn = iam.get_role(RoleName=ROLE)["Role"]["Arn"]
    except ClientError:
        role_arn = iam.create_role(RoleName=ROLE, AssumeRolePolicyDocument=json.dumps(trust))[
            "Role"
        ]["Arn"]
        iam.attach_role_policy(
            RoleName=ROLE,
            PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
        )
        time.sleep(12)  # new roles take a moment before Lambda can assume them

    code = zip_path.read_bytes()
    s3_args: dict = {}
    if len(code) > 49 * 1024 * 1024:
        s3 = boto3.client("s3")
        acct = boto3.client("sts").get_caller_identity()["Account"]
        region = lam.meta.region_name
        bucket = f"tangible-fit-{acct}-{region}"
        try:
            s3.head_bucket(Bucket=bucket)
        except ClientError:
            kw = (
                {}
                if region == "us-east-1"
                else {"CreateBucketConfiguration": {"LocationConstraint": region}}
            )
            s3.create_bucket(Bucket=bucket, **kw)
        s3.upload_file(str(zip_path), bucket, "fit.zip")
        s3_args = {"S3Bucket": bucket, "S3Key": "fit.zip"}

    try:
        lam.get_function(FunctionName=NAME)
        if s3_args:
            lam.update_function_code(FunctionName=NAME, **s3_args, Architectures=["arm64"])
        else:
            lam.update_function_code(FunctionName=NAME, ZipFile=code, Architectures=["arm64"])
    except ClientError:
        for attempt in range(5):
            try:
                lam.create_function(
                    FunctionName=NAME,
                    Runtime="python3.12",
                    Architectures=["arm64"],
                    Role=role_arn,
                    Handler="handler.handler",
                    Code=s3_args or {"ZipFile": code},
                    MemorySize=1024,
                    Timeout=30,
                    Description="Tangible fit check: OpenCV 5 footprint measurement from a photo",
                )
                break
            except ClientError as err:
                if "assume" not in str(err).lower() or attempt == 4:
                    raise
                time.sleep(8)
    lam.get_waiter("function_active_v2").wait(FunctionName=NAME)
    lam.get_waiter("function_updated_v2").wait(FunctionName=NAME)
    try:
        lam.put_function_concurrency(FunctionName=NAME, ReservedConcurrentExecutions=5)
    except ClientError as err:
        # new accounts have a total of 10 and must keep 10 unreserved; their whole-account
        # limit of 10 is then the cap instead
        if "UnreservedConcurrentExecution" not in str(err):
            raise

    try:
        url = lam.get_function_url_config(FunctionName=NAME)["FunctionUrl"]
    except ClientError:
        url = lam.create_function_url_config(
            FunctionName=NAME,
            AuthType="NONE",
            Cors={
                "AllowOrigins": ["*"],
                "AllowMethods": ["GET", "POST"],
                "AllowHeaders": ["content-type"],
            },
        )["FunctionUrl"]
    for sid, action, extra in (
        ("public-url", "lambda:InvokeFunctionUrl", {"FunctionUrlAuthType": "NONE"}),
        ("public-url-invoke", "lambda:InvokeFunction", {}),
    ):
        try:
            lam.add_permission(
                FunctionName=NAME, StatementId=sid, Action=action, Principal="*", **extra
            )
        except ClientError as err:
            if "ResourceConflict" not in str(err):
                raise
    print(url)  # noqa: T201
    return url


if __name__ == "__main__":
    z = build()
    if "--build" not in sys.argv:
        deploy(z)
