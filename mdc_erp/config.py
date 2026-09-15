"""Environment-based configuration.

Development  -> SQLite  (zero setup, single file erp.db)
Production   -> PostgreSQL via DATABASE_URL (Docker/Render/any host)

Select with FLASK_CONFIG=development|production (default: development,
automatically switching to production when DATABASE_URL points to Postgres).
"""
import os
import secrets
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DATA_DIR = os.environ.get('DATA_DIR', BASE_DIR)


class BaseConfig:
    # Development gets a per-process random key unless explicitly configured.
    # Production validation below requires SECRET_KEY from the deployment environment.
    SECRET_KEY = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping': True}
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    # Inactivity session timeout (sliding) — configurable via SESSION_TIMEOUT_MIN.
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=int(os.environ.get('SESSION_TIMEOUT_MIN', '60')))
    SESSION_REFRESH_EACH_REQUEST = True
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB uploads (backup restore, logos)


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'sqlite:///' + os.path.join(DATA_DIR, 'erp.db')
    ).replace('postgres://', 'postgresql://')


class ProductionConfig(BaseConfig):
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL', ''
    ).replace('postgres://', 'postgresql://')


CONFIGS = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
}


def _validate_production_environment():
    required = ('SECRET_KEY', 'JWT_SECRET_KEY', 'DB_PASSWORD', 'ENCRYPTION_KEY')
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError(
            'Production requires explicitly configured secrets: ' + ', '.join(missing)
        )
    secret = os.environ['SECRET_KEY']
    database_url = os.environ.get('DATABASE_URL', '')
    if len(secret) < 32:
        raise RuntimeError('Production requires SECRET_KEY with at least 32 characters.')
    if len(os.environ['JWT_SECRET_KEY']) < 32:
        raise RuntimeError('Production requires JWT_SECRET_KEY with at least 32 characters.')
    if len(os.environ['ENCRYPTION_KEY']) < 32:
        raise RuntimeError('Production requires ENCRYPTION_KEY with at least 32 characters.')
    if not database_url.startswith(('postgres://', 'postgresql://')):
        raise RuntimeError('Production requires DATABASE_URL pointing to PostgreSQL.')


def pick_config():
    name = os.environ.get('FLASK_CONFIG')
    if name == 'production':
        _validate_production_environment()
        return ProductionConfig
    if name == 'development':
        return DevelopmentConfig
    # A PostgreSQL URL is an explicit production signal; validate it rather
    # than silently accepting unsafe defaults.
    if (os.environ.get('DATABASE_URL') or '').startswith(('postgres://', 'postgresql://')):
        _validate_production_environment()
        return ProductionConfig
    return DevelopmentConfig
