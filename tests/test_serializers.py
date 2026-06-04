"""Tests for coruscant.utils.serializers.json_default()."""
import datetime
import decimal
import json
import uuid

import pytest

from coruscant.utils.serializers import json_default


# ---------------------------------------------------------------------------
# date / datetime / time
# ---------------------------------------------------------------------------

class TestDateTimeSerialization:
    def test_date(self):
        assert json_default(datetime.date(2024, 3, 15)) == "2024-03-15"

    def test_datetime(self):
        assert json_default(datetime.datetime(2024, 3, 15, 10, 30, 0)) == "2024-03-15T10:30:00"

    def test_datetime_with_microseconds(self):
        result = json_default(datetime.datetime(2024, 1, 1, 0, 0, 0, 500000))
        assert result.startswith("2024-01-01T00:00:00")

    def test_time(self):
        assert json_default(datetime.time(10, 30, 45)) == "10:30:45"

    def test_time_midnight(self):
        assert json_default(datetime.time(0, 0, 0)) == "00:00:00"

    def test_date_year_boundary(self):
        assert json_default(datetime.date(1, 1, 1)) == "0001-01-01"

    def test_datetime_max(self):
        result = json_default(datetime.datetime.max)
        assert isinstance(result, str)

    def test_time_with_microseconds(self):
        result = json_default(datetime.time(12, 0, 0, 123456))
        assert "12:00:00" in result


# ---------------------------------------------------------------------------
# Decimal
# ---------------------------------------------------------------------------

class TestDecimalSerialization:
    def test_integer_value(self):
        result = json_default(decimal.Decimal("42"))
        assert result == pytest.approx(42.0)
        assert isinstance(result, float)

    def test_fractional_value(self):
        result = json_default(decimal.Decimal("3.14"))
        assert result == pytest.approx(3.14)

    def test_negative_value(self):
        result = json_default(decimal.Decimal("-99.99"))
        assert result == pytest.approx(-99.99)

    def test_zero(self):
        assert json_default(decimal.Decimal("0")) == pytest.approx(0.0)

    def test_large_decimal(self):
        result = json_default(decimal.Decimal("1234567890.123456"))
        assert isinstance(result, float)

    def test_scientific_notation_decimal(self):
        result = json_default(decimal.Decimal("1E+5"))
        assert result == pytest.approx(100000.0)


# ---------------------------------------------------------------------------
# bytes
# ---------------------------------------------------------------------------

class TestBytesSerialization:
    def test_simple(self):
        assert json_default(b"\xde\xad\xbe\xef") == "deadbeef"

    def test_empty(self):
        assert json_default(b"") == ""

    def test_single_byte(self):
        assert json_default(b"\x0f") == "0f"

    def test_all_zeros(self):
        assert json_default(b"\x00\x00") == "0000"

    def test_ascii_bytes(self):
        result = json_default(b"hello")
        # hex of ASCII 'hello'
        assert result == "68656c6c6f"

    def test_high_bytes(self):
        result = json_default(b"\xff\xfe")
        assert result == "fffe"


# ---------------------------------------------------------------------------
# fallback (str)
# ---------------------------------------------------------------------------

class TestFallbackSerialization:
    def test_unknown_type_uses_str(self):
        class Custom:
            def __str__(self):
                return "custom_repr"
        assert json_default(Custom()) == "custom_repr"

    def test_none_fallback(self):
        # None should fall through to str(None) = "None"
        assert json_default(None) == "None"

    def test_list_fallback(self):
        result = json_default([1, 2, 3])
        assert result == "[1, 2, 3]"

    def test_set_fallback(self):
        result = json_default({42})
        assert "42" in result

    def test_custom_repr_with_special_chars(self):
        class Weird:
            def __str__(self):
                return "weird\tthing\nnewline"
        result = json_default(Weird())
        assert "weird" in result


# ---------------------------------------------------------------------------
# Integration: roundtrip through json.dumps / json.loads
# ---------------------------------------------------------------------------

class TestRoundtrip:
    def test_date(self):
        data = {"d": datetime.date(2024, 6, 1)}
        assert json.loads(json.dumps(data, default=json_default))["d"] == "2024-06-01"

    def test_datetime(self):
        data = {"dt": datetime.datetime(2024, 6, 1, 12, 0, 0)}
        assert json.loads(json.dumps(data, default=json_default))["dt"] == "2024-06-01T12:00:00"

    def test_decimal(self):
        data = {"amount": decimal.Decimal("9.99")}
        result = json.loads(json.dumps(data, default=json_default))
        assert result["amount"] == pytest.approx(9.99)

    def test_bytes(self):
        data = {"blob": b"\x00\x01\x02"}
        result = json.loads(json.dumps(data, default=json_default))
        assert result["blob"] == "000102"

    def test_mixed_record(self):
        record = {
            "id": 1,
            "created_at": datetime.datetime(2024, 1, 15, 9, 0, 0),
            "balance": decimal.Decimal("100.50"),
            "thumbnail": b"\xff\xd8",
        }
        parsed = json.loads(json.dumps(record, default=json_default))
        assert parsed["created_at"] == "2024-01-15T09:00:00"
        assert parsed["balance"] == pytest.approx(100.50)
        assert parsed["thumbnail"] == "ffd8"

    def test_nested_structure(self):
        data = {
            "rows": [
                {"ts": datetime.datetime(2024, 1, 1, 0, 0), "val": decimal.Decimal("1.5")},
                {"ts": datetime.datetime(2024, 1, 2, 0, 0), "val": decimal.Decimal("2.5")},
            ]
        }
        serialised = json.dumps(data, default=json_default)
        parsed = json.loads(serialised)
        assert parsed["rows"][0]["ts"] == "2024-01-01T00:00:00"
        assert parsed["rows"][1]["val"] == pytest.approx(2.5)

    def test_list_of_bytes(self):
        data = {"blobs": [b"\xaa", b"\xbb"]}
        parsed = json.loads(json.dumps(data, default=json_default))
        assert parsed["blobs"] == ["aa", "bb"]
