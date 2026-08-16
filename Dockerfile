FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium

# Copy source code
COPY . .

# Create necessary directories
RUN mkdir -p temp_downloads "Updated report"

# Start the bot
CMD ["python", "main.py"]
