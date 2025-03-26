FROM python:3.10-slim

# 작업 디렉토리 설정
WORKDIR /app

# Poetry 설치
RUN pip install poetry

# 프로젝트 파일 복사
COPY pyproject.toml poetry.lock ./
COPY alembic.ini ./
COPY iap/ ./iap/
COPY common/ ./common/
COPY worker/ ./worker/
COPY backoffice/ ./backoffice/
COPY app.py ./

# Poetry 설정: 가상환경 생성하지 않음
RUN poetry config virtualenvs.create false

# 의존성 설치 (main과 iap 그룹)
RUN poetry install --only main,iap,worker,backoffice

# 환경변수 설정
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# 애플리케이션 실행
CMD ["poetry", "run", "uvicorn", "backoffice.main:app", "--host", "0.0.0.0", "--port", "8000"]