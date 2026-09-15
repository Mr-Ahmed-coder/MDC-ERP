"""Development server.

    python run.py            SQLite, http://127.0.0.1:5000
    python run.py --demo     also loads demo data
    python run.py --online   listen on 0.0.0.0 (LAN access)
    python run.py --debug    Flask debug mode
"""
import os
import sys

# Optionally load a local .env for development convenience (DATABASE_URL, SECRET_KEY,
# etc.). Harmless if python-dotenv isn't installed, and never overrides variables
# already set in the real environment — so production behaviour is unchanged.
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from mdc_erp import create_app
from mdc_erp.bootstrap import init_db

app = create_app()
init_db(app, demo='--demo' in sys.argv)

if __name__ == '__main__':
    print('=' * 54)
    print('  Modern Diagnostic Center ERP')
    print('  http://127.0.0.1:5000    login: admin / configured INITIAL_ADMIN_PASSWORD')
    print('=' * 54)
    host = os.environ.get('HOST', '127.0.0.1')
    if '--host' in sys.argv or '--online' in sys.argv:
        host = '0.0.0.0'
    port = int(os.environ.get('PORT', '5000'))
    if host == '0.0.0.0':
        print('  LAN/Online mode: reachable at  http://<this-computer-ip>:%d' % port)
    app.run(debug='--debug' in sys.argv, host=host, port=port)
