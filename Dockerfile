FROM python:3.11-slim

LABEL org.opencontainers.image.source="https://github.com/AlexMasson/arr-llm-release-picker"
LABEL org.opencontainers.image.description="AI-powered release selection for Radarr using LLM"
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY run.py .

# Prompts must be mounted at /config/prompts
# Without prompts, AI is bypassed and Radarr chooses normally

ENV PORT=8080

EXPOSE 8080

# Single worker ensures consistent in-memory state across requests
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", "--timeout", "180", "app:app"]
