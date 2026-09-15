FROM python:3.12-slim
WORKDIR /app
# wkhtmltopdf + Chromium let the app render the exact print-view document to PDF
# for the Download button (identical to the browser Print). Chromium (via
# Playwright) is the preferred renderer; wkhtmltopdf is the fallback.
RUN apt-get update && apt-get install -y --no-install-recommends \
        wkhtmltopdf fonts-dejavu-core fonts-noto-core fontconfig \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-prod.txt ./
RUN pip install --no-cache-dir -r requirements-prod.txt
# Chromium for Playwright (installs the browser + its system dependencies)
RUN pip install --no-cache-dir playwright==1.47.0 \
    && playwright install --with-deps chromium
COPY . .
ENV DATA_DIR=/data PORT=8000 FLASK_CONFIG=production
RUN mkdir -p /data
EXPOSE 8000
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8000", "wsgi:app"]
