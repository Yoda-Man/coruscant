"""
coruscant.utils.serializers
~~~~~~~~~~~~~~~~~~~~~~~~~~~
JSON serialisation helpers for types that psycopg2 may return.

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

import datetime
import decimal


def json_default(obj: object) -> object:
    """
    Fallback serialiser for the standard ``json`` module.

    Handles: date, datetime, time, Decimal, bytes, and anything else
    (falls back to str()).
    """
    if isinstance(obj, (datetime.date, datetime.datetime, datetime.time)):
        return obj.isoformat()
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    if isinstance(obj, bytes):
        return obj.hex()
    return str(obj)
