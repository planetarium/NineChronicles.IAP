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

## Prerequisites
- [Poetry](https://python-poetry.org/)
- [yarn](https://yarnpkg.com/)

# Setup local development env.
## 1. Install packages
Install Python and JS packages to develop
```shell
# Install Python packages
poetry env use python3.10
poetry shell
poetry install
# Install JS packages
pushd frontend
yarn
popd
```

## 2. Setup database
`NineChronicles.IAP` manages DB schema using [alembic](https://alembic.sqlalchemy.org/en/latest/).
```shell
cp alembic.ini.example alembic.ini
```
Open alembic.ini file and edit `sqlalchemy.url` around line 60 to your local DB.  
Then use alembic command to migrate to latest DB schema.
```shell
alembic upgrade head
```

## 3. Run FastAPI application
`NineChronicles.IAP` uses [FastAPI](https://fastapi.tiangolo.com/) as backend.  
You should config your own settings to run backend app.
```shell
pushd iap/settings
cp local.py.example local.py
popd
```
Open iap/settings/local.py and set all values to your own.  
IAP validation URLs are set to validate sandbox receipts only. For production, you have to change these URLs to production URLs.

Now you can run backend app on your local env.
```shell
# Please check your poetry env. is enabled.
# If not, enable poetry env. using `poetry shell` command.
env=local uvicorn iap.main:app --reload
```
You can set `env=local` environment variable with your favorite ways.
