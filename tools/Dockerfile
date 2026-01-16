# Flow Generator for testing NetSentinel
FROM python:3.11-slim

WORKDIR /app

# Disable Python output buffering
ENV PYTHONUNBUFFERED=1

COPY flow_generator.py .

CMD ["python", "-u", "flow_generator.py", "--host", "collector", "--port", "2055", "--duration", "3600", "--anomaly-rate", "0.1"]
