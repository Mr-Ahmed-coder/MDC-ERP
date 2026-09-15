"""Small formatting/date helpers shared everywhere."""
import datetime as dt
from flask import request
from .security import setting

def money_round(n):
    """Round a monetary amount to whole cents using banker's-safe half-up.

    Every calculation that produces an amount to be stored or compared should
    pass through this so accumulated binary-float error (0.1+0.2 != 0.3) can
    never drift a balance by fractions of a cent. Kept as float for backward
    compatibility with the existing schema."""
    from decimal import Decimal, ROUND_HALF_UP
    try:
        return float(Decimal(str(n or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    except Exception:
        return round(float(n or 0), 2)


def money(n):
    n = float(n or 0); c = setting('currency', '$')
    s = f"{abs(n):,.0f}"
    return f"({c}{s})" if n < 0 else f"{c}{s}"
def today(): return dt.date.today().isoformat()
def cur_year(): return int(request.args.get('year', dt.date.today().year))

def log_error(context=''):
    """Log the active exception (with traceback) without interrupting flow.
    Use inside best-effort blocks so silent failures surface in mdc_erp.log
    instead of vanishing. Never raises."""
    try:
        from flask import current_app
        current_app.logger.exception('handled error: %s', context)
    except Exception:
        import logging, traceback
        logging.getLogger('mdc_erp').error('handled error: %s\n%s', context, traceback.format_exc())


def _radorder_count(rad_name):
    """Reports completed by a radiologist (Reported/Approved rad orders)."""
    from ..models import RadOrder
    return RadOrder.query.filter(RadOrder.radiologist == rad_name,
                                 RadOrder.status.in_(['Reported', 'Approved', 'Completed'])).count()
