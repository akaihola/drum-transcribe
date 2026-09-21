FROM docker.io/python:3.12-slim
WORKDIR /app
# openssh-client: gpu-session.sh delivers jobs to Vast instances over ssh
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY src ./src
# no-deps keeps the ML stack out; numpy is the one web-app import,
# boto3 syncs the bucket and presigns sources, vastai rents GPU instances
RUN pip install --no-deps --no-cache-dir . && pip install --no-cache-dir numpy boto3 vastai
COPY deploy/sync_bucket.py ./
COPY deploy/container-start.sh deploy/gpu-session.sh deploy/run-on-gpu.sh deploy/vast-worker.sh ./deploy/
ENV PORT=8080
CMD ["sh", "deploy/container-start.sh"]
