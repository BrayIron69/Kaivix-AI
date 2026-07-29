FROM python:3.11-slim

WORKDIR /app

# Copy requirements first so this layer is cached across builds that
# only change application code, not dependencies.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Everything else, minus what .dockerignore excludes (env files, *.db,
# .git, tests/, evals/, docs/ -- none of that belongs in a production
# image).
COPY . .

# Cloud Run injects PORT at runtime and requires the container to listen
# on 0.0.0.0 (not localhost/127.0.0.1) -- without this the platform's
# health check can never reach the container.
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
