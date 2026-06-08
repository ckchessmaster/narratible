FROM python:3.12-slim

# ML engine build args — set INSTALL_ML_ENGINES=true in docker-compose.gpu.yml
ARG INSTALL_ML_ENGINES=false
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu

WORKDIR /app

# System dependencies
# libsndfile1  — required by soundfile (audio I/O)
# libgomp1     — required by PyTorch (OpenMP)
# ffmpeg       — required by f5-tts/librosa (audio decode/encode)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    libgomp1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Core Python dependencies (edge-tts, FastAPI, PDF parsing, etc.)
COPY requirements.txt .
RUN grep -v '^\s*#' requirements.txt | grep -v '^\s*$' | pip install --no-cache-dir -r /dev/stdin

# Optional ML engines — skipped by default, included when INSTALL_ML_ENGINES=true
RUN if [ "${INSTALL_ML_ENGINES}" = "true" ]; then \
    pip install --no-cache-dir torch --index-url ${TORCH_INDEX_URL} && \
    pip install --no-cache-dir kokoro f5-tts; \
    fi

COPY . .

RUN mkdir -p projects

EXPOSE 8000

# Use uvicorn directly (no --reload) for container stability
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
