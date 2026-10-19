FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_ENV=production
WORKDIR /app

RUN useradd --create-home --uid 10001 app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app . .
RUN mkdir -p instance static/uploads && chown -R app:app instance static/uploads
USER app

EXPOSE 8000
# Apply migrations, then serve with Gunicorn (never the Flask dev server).
CMD ["sh", "-c", "flask --app wsgi db upgrade && gunicorn -c gunicorn.conf.py --bind 0.0.0.0:8000 wsgi:app"]
