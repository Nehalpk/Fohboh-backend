# Use official Python 3.11 image
FROM python:3.11

# Install necessary system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    libffi-dev \
    libssl-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file
COPY requirements.txt .

# Ensure PyCrypto is NOT installed and install dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip uninstall -y pycrypto && \
    pip install --no-cache-dir -r requirements.txt && \
    pip uninstall -y pycrypto && \
    pip install uvicorn

# Copy the application files
COPY . .

# Expose the application port (FastAPI default is 8000)
EXPOSE 8000

# Run FastAPI using Uvicorn
CMD ["uvicorn", "routes:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "5"]

