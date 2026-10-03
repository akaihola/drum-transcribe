FROM docker.io/python:3.12-slim
WORKDIR /app
# ffmpeg: yt-dlp audio extraction + ingest._as_source video handling
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY src ./src
# no-deps keeps the ML stack out; numpy is the one web-app import,
# boto3 reaches the buckets, yt-dlp fetches links (Vast: plain HTTP)
RUN pip install --no-deps --no-cache-dir . && pip install --no-cache-dir numpy boto3 yt-dlp
COPY deploy/sync_bucket.py ./
COPY deploy/container-start.sh ./deploy/
ENV PORT=8080
CMD ["sh", "deploy/container-start.sh"]
