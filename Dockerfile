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

# 2. Install Java 21 & Maven
RUN apt-get update && apt-get install -y \
    openjdk-21-jdk \
    maven \
    && rm -rf /var/lib/apt/lists/*
ENV JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64

# 3. Install Node.js (v22.x)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get update && apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# 4. Install .NET SDK (8.0 as it's the stable LTS on Ubuntu 22.04, compatible with most code)
# Microsoft package repo
RUN wget https://packages.microsoft.com/config/ubuntu/22.04/packages-microsoft-prod.deb -O packages-microsoft-prod.deb && \
    dpkg -i packages-microsoft-prod.deb && \
    rm packages-microsoft-prod.deb && \
    apt-get update && apt-get install -y dotnet-sdk-8.0 && \
    rm -rf /var/lib/apt/lists/*

# Install .NET global tools needed for Sandbox
RUN dotnet tool install -g dotnet-stryker
ENV PATH="$PATH:/root/.dotnet/tools"

# Create app directory
WORKDIR /app

# Install Python requirements
COPY requirements.txt .
# Add the new sandbox dependencies
RUN pip3 install --no-cache-dir -r requirements.txt
RUN pip3 install --no-cache-dir pytest pytest-cov mutmut nltk

# Download NLTK data for BLEU
RUN python3 -c "import nltk; nltk.download('punkt'); nltk.download('punkt_tab')"

# Copy the rest of the application
COPY . .

# Expose Web UI (7860) and API Server (8000)
EXPOSE 7860
EXPOSE 8000

# Default command to run the server and UI (through main.py)
CMD ["python", "main.py"]
