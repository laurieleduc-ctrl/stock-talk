FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy all application code first (needed for pyproject.toml to find README.md)
COPY . .

# Make start scripts executable
RUN chmod +x start.sh start-worker.sh

# Install Python dependencies
RUN pip install --no-cache-dir .

# Create non-root user
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Expose port (Railway will set PORT env var)
EXPOSE 8000

# Run the application via start script
CMD ["./start.sh"]
