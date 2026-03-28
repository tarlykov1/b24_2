FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY migration.config.yml.example ./migration.config.yml.example

RUN pip install --upgrade pip && pip install .

EXPOSE 8000

CMD ["uvicorn", "b24_migrator.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
