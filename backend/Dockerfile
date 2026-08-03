# OdontoQuiz Pipeline — Dockerfile (F2)
# Multi-purpose: API server, Celery worker, Flower monitor
FROM python:3.12-slim

WORKDIR /app

# System dependencies for PyMuPDF (PDF→image)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY backend/requirements.txt /app/backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy application code
COPY backend/ /app/backend/
COPY .git/ /app/.git/  # pydantic-settings may need it for version

# Run as non-root
RUN useradd -m -u 1000 odontoquiz && chown -R odontoquiz:odontoquiz /app
USER odontoquiz

# Default: API server
CMD ["uvicorn", "backend.src.main:app", "--host", "0.0.0.0", "--port", "8000"]
