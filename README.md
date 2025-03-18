# NineChronicles.IAP

Nine Chronicles In-app Purchase Service

<img src="https://img.shields.io/badge/Python-3.10-3776AB?style=for-the-badge&logo=python">
<img src="https://img.shields.io/badge/NodeJS-18.16.0-339933?style=for-the-badge&logo=nodedotjs">
<br>
<img src="https://img.shields.io/badge/AWS-Lambda-FF9900?style=for-the-badge&logo=awslambda">
<img src="https://img.shields.io/badge/Postgresql-15.2-4169E1?style=for-the-badge&logo=Postgresql">

---

# Requirements

## System requirements

- Python 3.10
- NodeJS 18 LTS
- Postgresql 15.2
- Docker & Docker Compose (선택사항)

## Prerequisites

- [Poetry](https://python-poetry.org/)
- [yarn](https://yarnpkg.com/)
- [AWS CDK](https://docs.aws.amazon.com/cdk/v2/guide/cli.html)
- [SAM](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/what-is-sam.html)

# Project Structure

NineChronicles.IAP has 4 parts mainly.
Each part is separated project and uses different virtualenv.
Please carefully check current env not to confuse which virtualenv to use.

## 1. NineChronicles.IAP (root)

[AWS CDK](https://docs.aws.amazon.com/cdk/v2/guide/home.html) to build and deploy services.
This project itself does not have any application/logic code in it.
If you want to manage AWS Stack and services, here is right place to see.

## 2. common

Common modules used from another services.
This manages DB model, revision and provides DB connector.

## 3. iap

Main service of NineChronicles.IAP.
This has FastAPI backend and Svelte Frontend backoffice.

## 4. worker

AWS Lambda worker functions to process message to NineChronicles Action and monitor blockchain.

# Setup local development env.

## 1. Using Docker Compose (권장)

Docker Compose를 사용하면 로컬 개발 환경을 쉽게 설정할 수 있습니다.

### 1. 환경 변수 설정

```bash
cp config.template .env
```

`.env` 파일을 열고 필요한 환경 변수들을 설정합니다. 주요 설정 항목:
- Database: PostgreSQL 연결 정보
- AWS: AWS 자격 증명
- Google: Google Service Account 정보
- Apple: Apple 인증 정보
- JWT: JWT 시크릿 키

### 2. 서비스 실행

```bash
# 서비스 시작
docker-compose up --build

# 백그라운드에서 실행
docker-compose up -d --build

# 서비스 중지
docker-compose down

# 로그 확인
docker-compose logs -f
```

### 3. 접속 정보

- 메인 앱: http://localhost:8000
- 백오피스: http://localhost:8001/products
- 데이터베이스: localhost:5432

## 2. Manual Setup (기존 방식)

## 1. Install packages

#### Warning

```text
Each project has own `pyproject.toml` and should be set on separated venv.
Please follow carefully instructions and double check everytime you work.
```

### 1. NineChronicles.IAP (root)

```shell
poetry env use python3.10
poetry shell
poetry install
exit # This does not close your terminal, exit from poetry venv session.
```

### 2. common

```shell
pushd common
poetry shell # Please make sure you have new poetry environment with seeing venv name
poetry install
exit
popd
```

### 2. iap

```shell
pushd iap
poetry shell # Please make sure you have new poetry environment with seeing venv name
poetry install
exit
popd
```

### 3. worker

```shell
pushd worker
poetry shell # Please make sure you have new poetry environment with seeing venv name
poetry install
exit
popd
```

## 2. Setup local database

`NineChronicles.IAP/common` manages DB schema using [alembic](https://alembic.sqlalchemy.org/en/latest/).
Please install PostgreSQL and run psql server before run alembic.

```shell
pushd common
poetry shell
cp alembic.ini.example alembic.ini
```

Open alembic.ini file and edit `sqlalchemy.url` around line 60 to your local DB.
Then use alembic command to migrate to latest DB schema.

```shell
alembic upgrade head
exit
popd
```

## 3. Run iap application

### 1. Frontend

`NineChronicles.IAP/iap` uses [Svelte]() ad frontend.
It can be served by vite, but we'll build fronetend app because it's closer to production.

```shell
cd iap/frontend
yarn
yarn build --watch  # Rebuild changes are detected
```

### 2. Backend

`NineChronicles.IAP/iap` uses [FastAPI](https://fastapi.tiangolo.com/) as backend.
You should config your own settings to run backend app.

```shell
cd iap/settings
cp local.py.example local.py
cd ..
```

Open iap/settings/local.py and set all values to your own.
IAP validation URLs are set to validate sandbox receipts only. For production, you have to change these URLs to
production URLs.

Now you can run backend app on your local env.

```shell
poetry shell
cd ..  # Move back to project root to import all packages and modules.
env=local uvicorn iap.main:app --reload
```

You can set `env=local` environment variable with your favorite ways.

# Build and deploy

NineChronicles.IAP uses [AWS CDK](https://docs.aws.amazon.com/cdk/v2/guide/cli.html) to build and deploy application to
AWS.

## 0. Setup your AWS account

There are several ways to deploy lambda functions to AWS.
In this document, only "IAM user with credentials" case is covered.

1. Create or select IAM user for CDK.
2. Setup IAM permissions.
   You can reference `iam_role_example.json` to check what permissions are required to where.
3. Create credentials and set it to your local machine.
    - You can set it to `~/.aws/credentials`

Replace `[AWS_PROFILE]` to your profile name in following commands.

## 1. Prepare Lambda Layer

Functions in NineChronicles.IAP cannot run itself without dependencies and AWS Lambda Layer ca do this.
Since we're managing packages using poetry, we need to make directory with dependent packages for lamda layer.

```shell
# For iap service
pushd iap
poetry shell
poetry export --without-hashes -o requirements.txt
pip install -r requirements.txt -t layer/python/lib/python3.10/site-packages/ --upgrade
exit
popd
# For worker
pushd worker
poetry shell
poetry export --without-hashes -o requirements.txt
pip install -r requirements.txt -t layer/python/lib/python3.10/site-packages/ --upgrade
exit
popd
```