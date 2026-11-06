"""Unit tests for the supported XSD datatypes and lexical rules."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from rag_foundry.ontology import datatypes as dt


def test_supported_datatypes_are_the_six_xsd_types():
    """The supported set holds exactly the documented datatypes."""
    assert dt.SUPPORTED_DATATYPES == {
        dt.XSD_STRING,
        dt.XSD_INTEGER,
        dt.XSD_DECIMAL,
        dt.XSD_BOOLEAN,
        dt.XSD_DATE,
        dt.XSD_DATE_TIME,
    }
    assert all(
        uri.startswith(dt.XSD_NAMESPACE) for uri in dt.SUPPORTED_DATATYPES
    )


@pytest.mark.parametrize(
    "value, expected",
    [
        ("text", "text"),
        (True, "true"),
        (False, "false"),
        (42, "42"),
        (Decimal("1E+2"), "100"),
        (Decimal("0.50"), "0.50"),
        (1.25, "1.25"),
        (date(2026, 11, 6), "2026-11-06"),
        (
            datetime(2026, 11, 6, 9, 30, tzinfo=timezone(timedelta(hours=7))),
            "2026-11-06T09:30:00+07:00",
        ),
    ],
)
def test_lexical_form(value, expected):
    """Python values convert to XSD lexical forms."""
    assert dt.lexical_form(value) == expected


@pytest.mark.parametrize(
    "datatype, text, valid",
    [
        (dt.XSD_STRING, "", True),
        (dt.XSD_INTEGER, "-17", True),
        (dt.XSD_INTEGER, "1_000", False),
        (dt.XSD_DECIMAL, "+.5", True),
        (dt.XSD_DECIMAL, ".", False),
        (dt.XSD_BOOLEAN, "1", True),
        (dt.XSD_BOOLEAN, "TRUE", False),
        (dt.XSD_DATE, "2024-02-29", True),
        (dt.XSD_DATE, "2023-02-29", False),
        (dt.XSD_DATE, "2026-11-06-14:00", True),
        (dt.XSD_DATE, "2026-11-06+14:60", False),
        (dt.XSD_DATE_TIME, "2026-11-06T23:59:59.999Z", True),
        (dt.XSD_DATE_TIME, "2026-11-06T23:60:00", False),
        (dt.XSD_DATE_TIME, "26-11-06T10:00:00", False),
    ],
)
def test_is_valid_lexical(datatype, text, valid):
    """Lexical spaces follow XSD, restricted to four-digit years."""
    assert dt.is_valid_lexical(datatype, text) is valid


def test_is_valid_lexical_rejects_unsupported_datatypes():
    """Unsupported datatypes are a programming error, not 'invalid'."""
    with pytest.raises(KeyError):
        dt.is_valid_lexical(dt.XSD_NAMESPACE + "gYear", "2026")


@pytest.mark.parametrize(
    "datatype, text, expected",
    [
        (dt.XSD_INTEGER, "+007", "7"),
        (dt.XSD_INTEGER, "-0", "0"),
        (dt.XSD_BOOLEAN, "0", "false"),
        (dt.XSD_BOOLEAN, "true", "true"),
        (dt.XSD_DECIMAL, "1.500", "1.5"),
        (dt.XSD_DECIMAL, "100", "100"),
        (dt.XSD_DECIMAL, "+.50", "0.5"),
        (dt.XSD_DECIMAL, "-001.50", "-1.5"),
        (dt.XSD_STRING, " Spaced ", " Spaced "),
        (dt.XSD_DATE, "2026-11-06Z", "2026-11-06Z"),
    ],
)
def test_canonical_form(datatype, text, expected):
    """Equal values share one canonical lexical form."""
    assert dt.canonical_form(datatype, text) == expected


@pytest.mark.parametrize(
    "datatype, text, valid",
    [
        (dt.XSD_DATE, "2026-11-06+14:00", True),
        (dt.XSD_DATE, "2026-11-06-14:00", True),
        (dt.XSD_DATE, "2026-11-06+14:59", False),
        (dt.XSD_DATE, "2026-11-06-14:01", False),
        (dt.XSD_DATE_TIME, "2026-11-06T10:00:00+13:59", True),
        (dt.XSD_DATE_TIME, "2026-11-06T10:00:00+14:30", False),
    ],
)
def test_timezone_offsets_stay_within_fourteen_hours(datatype, text, valid):
    """XSD limits timezone offsets to -14:00..+14:00 inclusive."""
    assert dt.is_valid_lexical(datatype, text) is valid


def test_decimal_canonical_form_is_exact():
    """Long decimals are never rounded into an allowed value."""
    first = "1.0000000000000000000000000001"
    second = "1.0000000000000000000000000002"
    assert dt.canonical_form(dt.XSD_DECIMAL, first) == first
    assert dt.canonical_form(dt.XSD_DECIMAL, first) != dt.canonical_form(
        dt.XSD_DECIMAL, second
    )
    assert dt.canonical_form(dt.XSD_DECIMAL, "1" * 40 + ".0") == "1" * 40


@pytest.mark.parametrize("text", ["0", "-0", "+0.000", "-.0", "0."])
def test_decimal_zero_has_one_canonical_form(text):
    """Every spelling of zero, signed or not, canonicalizes to '0'."""
    assert dt.canonical_form(dt.XSD_DECIMAL, text) == "0"
