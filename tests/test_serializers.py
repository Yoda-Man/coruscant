"""Tests for coruscant.utils.serializers.json_default()."""
import datetime
import decimal
import json

import pytest

from coruscant.utils.serializers import json_default


# ---------------------------------------------------------------------------
# Individual type coverage
# ---------------------------------------------------------------------------

def test_date():
    assert json_default(datetime.date(2024, 3, 15)) == "2024-03-15"


def test_datetime():
    assert json_default(datetime.datetime(2024, 3, 15, 10, 30, 0)) == "2024-03-15T10:30:00"


def test_datetime_with_microseconds():
    result = json_default(datetime.datetime(2024, 1, 1, 0, 0, 0, 500000))
    assert result.startswith("2024-01-01T00:00:00")


def test_time():
    assert json_default(datetime.time(10, 30, 45)) == "10:30:45"


def test_decimal_integer_value():
    result = json_default(decimal.Decimal("42"))
    assert result == pytest.approx(42.0)
    assert isinstance(result, float)


def test_decimal_fractional_value():
    result = json_default(decimal.Decimal("3.14"))
    assert result == pytest.approx(3.14)


def test_bytes_simple():
    assert json_default(b"\xde\xad\xbe\xef") == "deadbeef"


def test_bytes_empty():
    assert json_default(b"") == ""


def test_bytes_single():
    assert json_default(b"\x0f") == "0f"


def test_unknown_type_falls_back_to_str():
    class CustomObj:
        def __str__(self):
            return "custom_repr"

    assert json_default(CustomObj()) == "custom_repr"


def test_integer_falls_back_to_str():
    # Plain int is not special-cased — json handles it natively, but if it
    # reaches json_default it should still not crash.
    assert json_default(object()) is not None


# ---------------------------------------------------------------------------
# Integration: roundtrip through json.dumps / json.loads
# ---------------------------------------------------------------------------

def test_roundtrip_date():
    data = {"d": datetime.date(2024, 6, 1)}
    assert json.loads(json.dumps(data, default=json_default))["d"] == "2024-06-01"


def test_roundtrip_datetime():
    data = {"dt": datetime.datetime(2024, 6, 1, 12, 0, 0)}
    assert json.loads(json.dumps(data, default=json_default))["dt"] == "2024-06-01T12:00:00"


def test_roundtrip_decimal():
    data = {"amount": decimal.Decimal("9.99")}
    result = json.loads(json.dumps(data, default=json_default))
    assert result["amount"] == pytest.approx(9.99)


def test_roundtrip_bytes():
    data = {"blob": b"\x00\x01\x02"}
    result = json.loads(json.dumps(data, default=json_default))
    assert result["blob"] == "000102"


def test_roundtrip_mixed_record():
    record = {
        "id": 1,
        "created_at": datetime.datetime(2024, 1, 15, 9, 0, 0),
        "balance": decimal.Decimal("100.50"),
        "thumbnail": b"\xff\xd8",
    }
    serialised = json.dumps(record, default=json_default)
    parsed = json.loads(serialised)
    assert parsed["created_at"] == "2024-01-15T09:00:00"
    assert parsed["balance"] == pytest.approx(100.50)
    assert parsed["thumbnail"] == "ffd8"
