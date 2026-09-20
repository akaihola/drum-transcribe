FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
# no-deps keeps the ML stack out; numpy is the one dep the web app imports
RUN pip install --no-deps --no-cache-dir . && pip install --no-cache-dir numpy
COPY output ./output
ENV PORT=8080
CMD ["sh", "-c", "drum-transcribe serve /app/output --host 0.0.0.0 --port ${PORT}"]
