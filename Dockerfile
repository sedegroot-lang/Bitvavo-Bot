# Bitvavo Trading Bot - Production Dockerfile
# Multi-stage build for optimized production image

FROM python:3.11-slim as builder

# Build arguments
ARG BUILD_DATE
ARG VCS_REF
ARG VERSION

# Metadata
LABEL maintainer="Bitvavo Bot" \
      description="Automated cryptocurrency trading bot for Bitvavo exchange" \
      version="${VERSION}" \
      build_date="${BUILD_DATE}" \
      vcs_ref="${VCS_REF}"

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements
COPY requirements.txt /tmp/requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /tmp/requirements.txt

# ==========================================
# Final production image
# ==========================================
FROM python:3.11-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create app user (non-root for security)
RUN useradd --create-home --shell /bin/bash botuser

# Set working directory
WORKDIR /app

# Copy application code
COPY --chown=botuser:botuser . /app

# Create data directories
RUN mkdir -p /app/data /app/logs /app/backups /app/metrics /app/reports && \
    chown -R botuser:botuser /app

# Switch to non-root user
USER botuser

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LOG_LEVEL=INFO

# Expose ports (5002 = Dashboard V2)
EXPOSE 5002

# Health check — uses Dashboard V2 health endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:5002/api/health || exit 1

# Default command (can be overridden in docker-compose.yml)
CMD ["python", "scripts/startup/start_bot.py"]
