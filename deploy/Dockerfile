FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-deps --no-cache-dir .
COPY output ./output
ENV PORT=8080
CMD ["sh", "-c", "drum-transcribe serve /app/output --host 0.0.0.0 --port ${PORT}"]
