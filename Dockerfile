# Base image: Ubuntu 22.04 LTS
FROM ubuntu:22.04

# Prevent interactive prompts during apt-get
ENV DEBIAN_FRONTEND=noninteractive

# Install common utilities
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    gnupg \
    software-properties-common \
    git \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# 1. Install Python 3.10 and pip
RUN add-apt-repository ppa:deadsnakes/ppa -y && \
    apt-get update && apt-get install -y \
    python3.10 \
    python3.10-dev \
    python3.10-distutils \
    python3-pip \
    python3.10-venv && \
    rm -rf /var/lib/apt/lists/*
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1 && \
    update-alternatives --install /usr/bin/python python /usr/bin/python3.10 1

# Dedicated identity for executing AI-generated tests. Do not reuse Ubuntu's
# global `nobody` account: RLIMIT_NPROC is counted per real UID, so unrelated
# processes using `nobody` can make exec() fail with EAGAIN.
ARG UTCODER_SANDBOX_UID=10001
ARG UTCODER_SANDBOX_GID=10001
RUN groupadd --gid "${UTCODER_SANDBOX_GID}" utcoder-sandbox && \
    useradd --uid "${UTCODER_SANDBOX_UID}" \
            --gid "${UTCODER_SANDBOX_GID}" \
            --no-create-home \
            --home-dir /nonexistent \
            --shell /usr/sbin/nologin \
            utcoder-sandbox
ENV UTCODER_SANDBOX_USER=utcoder-sandbox

# Create app directory
WORKDIR /app

# Install Python requirements
COPY requirements.txt .
COPY core/sandbox/requirements-eval.txt ./core/sandbox/requirements-eval.txt
# Install the application plus the exact Ubuntu benchmark evaluator stack.
RUN pip3 install --no-cache-dir \
    -r requirements.txt \
    -r core/sandbox/requirements-eval.txt

# Copy the rest of the application
COPY . .

# Expose Web UI (7860) and API Server (8000)
EXPOSE 7860
EXPOSE 8000

# Default command to run the server and UI (through main.py)
CMD ["python", "main.py"]
