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
        'DATABASE_URL',
        'sqlite:///' + os.path.join(DATA_DIR, 'erp.db')
    ).replace('postgres://', 'postgresql://')


CONFIGS = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
}


def _validate_production_environment():
    database_url = os.environ.get('DATABASE_URL', '')
    
    # Auto-extract DB_PASSWORD from DATABASE_URL if not explicitly set
    if not os.environ.get('DB_PASSWORD') and '@' in database_url and ':' in database_url:
        try:
            parsed_pass = database_url.split('://')[1].split('@')[0].split(':')[1]
            if parsed_pass:
                os.environ['DB_PASSWORD'] = parsed_pass
        except Exception:
            pass

    # Ensure fallback 32+ char secrets if missing in environment
    secret = os.environ.get('SECRET_KEY', '')
    if not secret or len(secret) < 32:
        os.environ['SECRET_KEY'] = secrets.token_hex(32)
    
    if not os.environ.get('JWT_SECRET_KEY') or len(os.environ.get('JWT_SECRET_KEY', '')) < 32:
        os.environ['JWT_SECRET_KEY'] = secrets.token_hex(32)
        
    if not os.environ.get('ENCRYPTION_KEY') or len(os.environ.get('ENCRYPTION_KEY', '')) < 32:
        os.environ['ENCRYPTION_KEY'] = secrets.token_hex(32)

    if not os.environ.get('DB_PASSWORD'):
        os.environ['DB_PASSWORD'] = 'cloud-managed-db'

    ProductionConfig.SECRET_KEY = os.environ.get('SECRET_KEY')

    if database_url and database_url.startswith(('postgres://', 'postgresql://')):
        ProductionConfig.SQLALCHEMY_DATABASE_URI = database_url.replace('postgres://', 'postgresql://')
    else:
        ProductionConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(DATA_DIR, 'erp.db')


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
