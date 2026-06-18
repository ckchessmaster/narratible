# GPU-enabled backend image.
FROM nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# System audio/ML deps (ffmpeg for f5-tts, libsndfile for soundfile)
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.11 \
        python3.11-venv \
        python3.11-dev \
        python3-pip \
        libsndfile1 \
        libgomp1 \
        ffmpeg \
        curl \
        git \
    && rm -rf /var/lib/apt/lists/*

RUN ln -s /usr/bin/python3.11 /usr/bin/python

# Install PyTorch 2.5.1 for CUDA 12.4
RUN python -m pip install --no-cache-dir "torch==2.5.1" "torchvision==0.20.1" "torchaudio==2.5.1" --index-url https://download.pytorch.org/whl/cu124

# Core app dependencies
COPY requirements.txt .
RUN python -m pip install --upgrade pip && \
    grep -v '^\s*#' requirements.txt | grep -v '^\s*$' | python -m pip install --no-cache-dir -r /dev/stdin

# Kokoro + F5-TTS voice engines (torchcodec removed — not needed for TTS)
RUN python -m pip install --no-cache-dir kokoro f5-tts git+https://github.com/huggingface/transformers.git && \
    python -m pip uninstall -y torchcodec

COPY . .
RUN mkdir -p projects

EXPOSE 8000
CMD ["/bin/sh", "-c", "if [ \"${UVICORN_ACCESS_LOG:-0}\" = \"1\" ]; then exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000; else exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log; fi"]
