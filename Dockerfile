FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY bot ./bot
COPY dashboard ./dashboard

RUN pip install --no-cache-dir .

RUN mkdir -p /app/data

CMD ["python", "-m", "bot"]
