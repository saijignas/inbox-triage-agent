FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt requirements-gemini.txt ./
# Set --build-arg WITH_GEMINI=1 to include the optional google-genai SDK.
ARG WITH_GEMINI=0
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$WITH_GEMINI" = "1" ]; then pip install --no-cache-dir -r requirements-gemini.txt; fi

COPY app ./app
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
