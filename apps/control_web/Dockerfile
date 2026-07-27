FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system app \
    && adduser --system --ingroup app app

COPY requirements.txt /app/requirements.txt

RUN python -m pip install \
    --no-cache-dir \
    --requirement /app/requirements.txt

COPY app.py /app/app.py
COPY entity_api.py /app/entity_api.py
COPY wsgi.py /app/wsgi.py
COPY pipeline_ui.py /app/pipeline_ui.py
COPY templates /app/templates
COPY static /app/static

RUN chown -R app:app /app

USER app

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "4", "--timeout", "60", "wsgi:app"]