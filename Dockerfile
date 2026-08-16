FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Copy requirements and install. Playwright version MUST match the image tag
# (pip ">=1.49" previously pulled 1.62 and then looked for a missing browser).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Create necessary directories
RUN mkdir -p temp_downloads "Updated report"

# Start the bot
CMD ["python", "main.py"]
