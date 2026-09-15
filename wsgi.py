"""Production entry point.

    gunicorn -w 4 -b 0.0.0.0:8000 wsgi:app        (Linux / Docker)
    waitress-serve --port=8000 wsgi:app           (Windows)
"""
from mdc_erp import create_app

app = create_app()
# Production startup is intentionally side-effect free. Run `flask db upgrade`
# and the explicit initialization command before starting Gunicorn.

if __name__ == '__main__':
    app.run()
