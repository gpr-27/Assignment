FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY ui ./ui

# Don't run as root.
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8001 8502
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
