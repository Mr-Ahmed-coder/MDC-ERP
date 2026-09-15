"""Reset the administrator login to a known username / password.

Usage (from the project folder):
    python reset_admin.py                 # sets  admin / admin123
    python reset_admin.py admin MyPass99  # sets a custom username / password

DEV / LOCAL CONVENIENCE ONLY. A short password like "admin123" is NOT safe on a
live system that holds real patient data — change it to a strong, private one
before going live (Settings, or re-run this with your own password).
"""
import os
import sys

os.environ.setdefault('FLASK_CONFIG', 'development')

from mdc_erp import create_app
from mdc_erp.extensions import db
from mdc_erp.models import User
from werkzeug.security import generate_password_hash

USERNAME = sys.argv[1] if len(sys.argv) > 1 else 'admin'
PASSWORD = sys.argv[2] if len(sys.argv) > 2 else 'admin123'

app = create_app()
with app.app_context():
    # Prefer an existing 'admin', else the first super_admin, else the first user.
    u = (User.query.filter_by(username=USERNAME).first()
         or User.query.filter_by(role='super_admin').first()
         or User.query.first())
    if not u:
        print('No user exists yet. Start the app once to create the administrator, '
              'then run this script again.')
        sys.exit(1)
    u.username = USERNAME
    u.pw = generate_password_hash(PASSWORD)
    u.must_change_pw = False
    u.active = True
    db.session.commit()
    print(f'OK - you can now log in with:  {USERNAME} / {PASSWORD}')
