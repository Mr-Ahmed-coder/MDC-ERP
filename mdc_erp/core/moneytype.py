"""Exact monetary storage.

`Money` is a SQLAlchemy type that stores amounts as **integer cents** in the
database while presenting ordinary floats (dollars) to the application. That
gives two guarantees the previous plain-Float columns could not:

  1. Nothing fractional-of-a-cent can ever be persisted — every write is
     rounded half-up at the storage boundary.
  2. Values in the database are exact integers, so SUM/GROUP BY in SQL and
     round-tripping through backups never drift.

Python-side arithmetic is unchanged (still floats), so no business logic had to
be rewritten; combined with `money_round()` in the calculation layer, amounts
are correct end to end.

NOTE: SQLAlchemy applies this type's result processor to aggregates as well, so
``func.sum(Model.money_col)`` already returns dollars — do **not** divide again.
:func:`cents_to_amount` is provided only for genuinely raw SQL (``text()``)
that bypasses the ORM entirely.
"""
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import Integer
from sqlalchemy.types import TypeDecorator


def to_cents(value):
    """Python amount (dollars) -> integer cents, half-up. None stays None."""
    if value is None or value == '':
        return None
    try:
        d = Decimal(str(value))
    except Exception:
        return None
    return int((d * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def cents_to_amount(cents):
    """Integer cents -> float dollars. Use for raw SQL aggregate results."""
    if cents is None:
        return 0.0
    return round(int(cents) / 100.0, 2)


class Money(TypeDecorator):
    """INTEGER cents in the database, float dollars in Python."""
    impl = Integer
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return to_cents(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return round(int(value) / 100.0, 2)
