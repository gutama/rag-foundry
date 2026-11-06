"""The supported XSD datatypes and their lexical rules (ADR-0011).

Shared by the models, which refuse allowed values outside a property's
datatype, and the constraint validator, which checks literal values.
"""

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable, Dict

XSD_NAMESPACE = "http://www.w3.org/2001/XMLSchema#"

XSD_STRING = XSD_NAMESPACE + "string"
XSD_INTEGER = XSD_NAMESPACE + "integer"
XSD_DECIMAL = XSD_NAMESPACE + "decimal"
XSD_BOOLEAN = XSD_NAMESPACE + "boolean"
XSD_DATE = XSD_NAMESPACE + "date"
XSD_DATE_TIME = XSD_NAMESPACE + "dateTime"

SUPPORTED_DATATYPES = frozenset(
    (
        XSD_STRING,
        XSD_INTEGER,
        XSD_DECIMAL,
        XSD_BOOLEAN,
        XSD_DATE,
        XSD_DATE_TIME,
    )
)

_INTEGER = re.compile(r"^[+-]?[0-9]+$")
_DECIMAL = re.compile(r"^[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)$")
_TIMEZONE = r"(Z|[+-](?P<tzh>[0-9]{2}):(?P<tzm>[0-9]{2}))?"
_DATE = re.compile(
    r"^(?P<y>[0-9]{4})-(?P<mo>[0-9]{2})-(?P<d>[0-9]{2})" + _TIMEZONE + "$"
)
_DATE_TIME = re.compile(
    r"^(?P<y>[0-9]{4})-(?P<mo>[0-9]{2})-(?P<d>[0-9]{2})"
    r"T(?P<h>[0-9]{2}):(?P<mi>[0-9]{2}):(?P<s>[0-9]{2})(\.[0-9]+)?"
    + _TIMEZONE
    + "$"
)
_BOOLEANS = {"true": "true", "1": "true", "false": "false", "0": "false"}


def lexical_form(value: Any) -> str:
    """Convert a Python value to an XSD lexical form.

    Args:
        value: A string (returned unchanged), bool, int, Decimal, float,
            date or datetime.

    Returns:
        The lexical form.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _valid_timezone(match: "re.Match[str]") -> bool:
    """Check the optional ±hh:mm timezone, limited to ±14:00 by XSD."""
    hours, minutes = match.group("tzh"), match.group("tzm")
    if hours is None:
        return True
    offset = int(hours) * 60 + int(minutes)
    return int(minutes) <= 59 and offset <= 14 * 60


def _is_date(text: str) -> bool:
    """Check the xsd:date lexical space (four-digit years)."""
    match = _DATE.match(text)
    if match is None or not _valid_timezone(match):
        return False
    try:
        date(int(match["y"]), int(match["mo"]), int(match["d"]))
    except ValueError:
        return False
    return True


def _is_date_time(text: str) -> bool:
    """Check the xsd:dateTime lexical space (four-digit years)."""
    match = _DATE_TIME.match(text)
    if match is None or not _valid_timezone(match):
        return False
    try:
        datetime(
            int(match["y"]), int(match["mo"]), int(match["d"]),
            int(match["h"]), int(match["mi"]), int(match["s"]),
        )
    except ValueError:
        return False
    return True


_LEXICAL_CHECKS: Dict[str, Callable[[str], bool]] = {
    XSD_STRING: lambda text: True,
    XSD_INTEGER: lambda text: bool(_INTEGER.match(text)),
    XSD_DECIMAL: lambda text: bool(_DECIMAL.match(text)),
    XSD_BOOLEAN: lambda text: text in _BOOLEANS,
    XSD_DATE: _is_date,
    XSD_DATE_TIME: _is_date_time,
}


def is_valid_lexical(datatype: str, text: str) -> bool:
    """Check that text is in the lexical space of a supported datatype.

    Args:
        datatype: One of ``SUPPORTED_DATATYPES``.
        text: Candidate lexical form.

    Returns:
        True if the text is a valid lexical form of the datatype.

    Raises:
        KeyError: If the datatype is not supported.
    """
    return _LEXICAL_CHECKS[datatype](text)


def canonical_form(datatype: str, text: str) -> str:
    """Canonicalize a valid lexical form so equal values compare equal.

    Integers lose signs and leading zeros, booleans become ``true`` or
    ``false``, and decimals lose trailing zeros. Other datatypes are
    compared as written.

    Args:
        datatype: One of ``SUPPORTED_DATATYPES``.
        text: A lexical form valid for the datatype.

    Returns:
        The canonical lexical form.
    """
    if datatype == XSD_INTEGER:
        return str(int(text))
    if datatype == XSD_BOOLEAN:
        return _BOOLEANS[text]
    if datatype == XSD_DECIMAL:
        return _canonical_decimal(text)
    return text


def _canonical_decimal(text: str) -> str:
    """Canonicalize a valid xsd:decimal exactly, without a decimal context.

    ``Decimal.normalize`` would round to the context precision (28 digits by
    default), making distinct long values compare equal, so the lexical
    form is rewritten as text instead: no leading or fractional trailing
    zeros, no "+" sign, and a single unsigned zero.
    """
    negative = text.startswith("-")
    integer, _, fraction = text.lstrip("+-").partition(".")
    integer = integer.lstrip("0") or "0"
    fraction = fraction.rstrip("0")
    digits = integer + ("." + fraction if fraction else "")
    if digits == "0" or not negative:
        return digits
    return "-" + digits
