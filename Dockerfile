FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files first for layer caching.
COPY pyproject.toml setup.py README.md ./

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Copy application code
COPY . .

# Bake the build commit for /version (see loobric_server/version.py: the env
# override is the only way an installed build can know its commit).
ARG LOOBRIC_COMMIT=""
ENV LOOBRIC_COMMIT=$LOOBRIC_COMMIT

# Create non-root user. /app/data must exist and be owned by the app user
# BEFORE the USER switch: a fresh named volume mounted there inherits the
# image directory's ownership, so `docker run -v loobric-data:/app/data`
# works out of the box instead of handing uid 1000 a root-owned mount.
RUN useradd -m -u 1000 loobric_server \
    && mkdir -p /app/data \
    && chown -R loobric_server:loobric_server /app
USER loobric_server

# Expose port
EXPOSE 8000

# Default command (can be overridden in docker-compose)
CMD ["uvicorn", "loobric_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
