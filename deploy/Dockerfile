FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
# no-deps keeps the ML stack out; numpy is the one web-app import, boto3 syncs the bucket
RUN pip install --no-deps --no-cache-dir . && pip install --no-cache-dir numpy boto3
COPY deploy/sync_bucket.py ./
ENV PORT=8080
CMD ["sh", "-c", "python sync_bucket.py /app/output && drum-transcribe serve /app/output --host 0.0.0.0 --port ${PORT}"]
