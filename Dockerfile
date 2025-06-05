# Use Python 3.10 slim image for smaller size
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create downloads directory
RUN mkdir -p /app/downloads

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=app.py
ENV FLASK_ENV=production
ENV PORT=10000

# Expose port (Render will use $PORT environment variable)
EXPOSE $PORT

# Set memory limits for Python
ENV PYTHONMALLOC=malloc
ENV PYTHONFAULTHANDLER=1
ENV PYTHONHASHSEED=random

# Run the application with Gunicorn
CMD gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 2 --timeout 120 --worker-class gthread app:app
