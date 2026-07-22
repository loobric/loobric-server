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

# Create non-root user
RUN useradd -m -u 1000 loobric_server && chown -R loobric_server:loobric_server /app
USER loobric_server

# Expose port
EXPOSE 8000

# Default command (can be overridden in docker-compose)
CMD ["uvicorn", "loobric_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
