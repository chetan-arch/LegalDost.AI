FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY pyproject.toml ./
COPY legaldost ./legaldost
RUN pip install ".[postgres]"

COPY alembic.ini ./
COPY migrations ./migrations
COPY knowledge ./knowledge
COPY eval ./eval

RUN useradd --create-home --uid 10001 app && mkdir -p /app/data && chown app /app/data
USER app

EXPOSE 8000
CMD ["sh", "-c", "legaldost db upgrade && uvicorn --factory legaldost.api.app:app_factory --host 0.0.0.0 --port 8000 --proxy-headers"]
