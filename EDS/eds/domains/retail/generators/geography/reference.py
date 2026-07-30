"""Curated real-world geography reference data.

Countries and their subdivisions are real: invented country codes or states
would break the "realistic" and "referentially correct" requirements, and no
random process can produce a valid ISO code. Cities are synthesised on top of
this fixed backbone, so a city always belongs to a real state and a state
always belongs to a real country.

Bounding boxes are approximate mainland extents, used to place cities at
plausible coordinates.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["COUNTRY_REFERENCE", "CountryReference", "StateReference", "supported_countries"]


@dataclass(frozen=True, slots=True)
class StateReference:
    """A real first-level administrative subdivision.

    Attributes:
        code: Subdivision code, unique within its country.
        name: Subdivision name.
    """

    code: str
    name: str


@dataclass(frozen=True, slots=True)
class CountryReference:
    """A real country and its subdivisions.

    Attributes:
        code: ISO 3166-1 alpha-2 code.
        code_3: ISO 3166-1 alpha-3 code.
        name: Country name.
        currency_code: ISO 4217 currency code.
        phone_code: International dialling prefix.
        region: Broad geographic region.
        postal_format: Template where ``#`` is a digit and ``@`` a letter.
        latitude_range: Approximate (min, max) latitude of the mainland.
        longitude_range: Approximate (min, max) longitude of the mainland.
        timezones: IANA timezones used within the country.
        states: First-level subdivisions.
    """

    code: str
    code_3: str
    name: str
    currency_code: str
    phone_code: str
    region: str
    postal_format: str
    latitude_range: tuple[float, float]
    longitude_range: tuple[float, float]
    timezones: tuple[str, ...]
    states: tuple[StateReference, ...]


_US_STATES: tuple[StateReference, ...] = (
    StateReference("AL", "Alabama"),
    StateReference("AK", "Alaska"),
    StateReference("AZ", "Arizona"),
    StateReference("AR", "Arkansas"),
    StateReference("CA", "California"),
    StateReference("CO", "Colorado"),
    StateReference("CT", "Connecticut"),
    StateReference("DE", "Delaware"),
    StateReference("DC", "District of Columbia"),
    StateReference("FL", "Florida"),
    StateReference("GA", "Georgia"),
    StateReference("HI", "Hawaii"),
    StateReference("ID", "Idaho"),
    StateReference("IL", "Illinois"),
    StateReference("IN", "Indiana"),
    StateReference("IA", "Iowa"),
    StateReference("KS", "Kansas"),
    StateReference("KY", "Kentucky"),
    StateReference("LA", "Louisiana"),
    StateReference("ME", "Maine"),
    StateReference("MD", "Maryland"),
    StateReference("MA", "Massachusetts"),
    StateReference("MI", "Michigan"),
    StateReference("MN", "Minnesota"),
    StateReference("MS", "Mississippi"),
    StateReference("MO", "Missouri"),
    StateReference("MT", "Montana"),
    StateReference("NE", "Nebraska"),
    StateReference("NV", "Nevada"),
    StateReference("NH", "New Hampshire"),
    StateReference("NJ", "New Jersey"),
    StateReference("NM", "New Mexico"),
    StateReference("NY", "New York"),
    StateReference("NC", "North Carolina"),
    StateReference("ND", "North Dakota"),
    StateReference("OH", "Ohio"),
    StateReference("OK", "Oklahoma"),
    StateReference("OR", "Oregon"),
    StateReference("PA", "Pennsylvania"),
    StateReference("RI", "Rhode Island"),
    StateReference("SC", "South Carolina"),
    StateReference("SD", "South Dakota"),
    StateReference("TN", "Tennessee"),
    StateReference("TX", "Texas"),
    StateReference("UT", "Utah"),
    StateReference("VT", "Vermont"),
    StateReference("VA", "Virginia"),
    StateReference("WA", "Washington"),
    StateReference("WV", "West Virginia"),
    StateReference("WI", "Wisconsin"),
    StateReference("WY", "Wyoming"),
)

_CA_STATES: tuple[StateReference, ...] = (
    StateReference("AB", "Alberta"),
    StateReference("BC", "British Columbia"),
    StateReference("MB", "Manitoba"),
    StateReference("NB", "New Brunswick"),
    StateReference("NL", "Newfoundland and Labrador"),
    StateReference("NS", "Nova Scotia"),
    StateReference("NT", "Northwest Territories"),
    StateReference("NU", "Nunavut"),
    StateReference("ON", "Ontario"),
    StateReference("PE", "Prince Edward Island"),
    StateReference("QC", "Quebec"),
    StateReference("SK", "Saskatchewan"),
    StateReference("YT", "Yukon"),
)

_GB_STATES: tuple[StateReference, ...] = (
    StateReference("ENG", "England"),
    StateReference("SCT", "Scotland"),
    StateReference("WLS", "Wales"),
    StateReference("NIR", "Northern Ireland"),
)

_AU_STATES: tuple[StateReference, ...] = (
    StateReference("NSW", "New South Wales"),
    StateReference("VIC", "Victoria"),
    StateReference("QLD", "Queensland"),
    StateReference("SA", "South Australia"),
    StateReference("WA", "Western Australia"),
    StateReference("TAS", "Tasmania"),
    StateReference("NT", "Northern Territory"),
    StateReference("ACT", "Australian Capital Territory"),
)

_DE_STATES: tuple[StateReference, ...] = (
    StateReference("BW", "Baden-Wurttemberg"),
    StateReference("BY", "Bavaria"),
    StateReference("BE", "Berlin"),
    StateReference("BB", "Brandenburg"),
    StateReference("HB", "Bremen"),
    StateReference("HH", "Hamburg"),
    StateReference("HE", "Hesse"),
    StateReference("MV", "Mecklenburg-Vorpommern"),
    StateReference("NI", "Lower Saxony"),
    StateReference("NW", "North Rhine-Westphalia"),
    StateReference("RP", "Rhineland-Palatinate"),
    StateReference("SL", "Saarland"),
    StateReference("SN", "Saxony"),
    StateReference("ST", "Saxony-Anhalt"),
    StateReference("SH", "Schleswig-Holstein"),
    StateReference("TH", "Thuringia"),
)

_IN_STATES: tuple[StateReference, ...] = (
    StateReference("AP", "Andhra Pradesh"),
    StateReference("AR", "Arunachal Pradesh"),
    StateReference("AS", "Assam"),
    StateReference("BR", "Bihar"),
    StateReference("CT", "Chhattisgarh"),
    StateReference("DL", "Delhi"),
    StateReference("GA", "Goa"),
    StateReference("GJ", "Gujarat"),
    StateReference("HR", "Haryana"),
    StateReference("HP", "Himachal Pradesh"),
    StateReference("JH", "Jharkhand"),
    StateReference("KA", "Karnataka"),
    StateReference("KL", "Kerala"),
    StateReference("MP", "Madhya Pradesh"),
    StateReference("MH", "Maharashtra"),
    StateReference("MN", "Manipur"),
    StateReference("ML", "Meghalaya"),
    StateReference("MZ", "Mizoram"),
    StateReference("NL", "Nagaland"),
    StateReference("OR", "Odisha"),
    StateReference("PB", "Punjab"),
    StateReference("RJ", "Rajasthan"),
    StateReference("SK", "Sikkim"),
    StateReference("TN", "Tamil Nadu"),
    StateReference("TG", "Telangana"),
    StateReference("TR", "Tripura"),
    StateReference("UP", "Uttar Pradesh"),
    StateReference("UT", "Uttarakhand"),
    StateReference("WB", "West Bengal"),
)

COUNTRY_REFERENCE: tuple[CountryReference, ...] = (
    CountryReference(
        code="US",
        code_3="USA",
        name="United States",
        currency_code="USD",
        phone_code="+1",
        region="North America",
        postal_format="#####",
        latitude_range=(24.5, 49.0),
        longitude_range=(-124.8, -66.9),
        timezones=(
            "America/New_York",
            "America/Chicago",
            "America/Denver",
            "America/Los_Angeles",
        ),
        states=_US_STATES,
    ),
    CountryReference(
        code="CA",
        code_3="CAN",
        name="Canada",
        currency_code="CAD",
        phone_code="+1",
        region="North America",
        postal_format="@#@ #@#",
        latitude_range=(43.0, 60.0),
        longitude_range=(-135.0, -52.6),
        timezones=("America/Toronto", "America/Winnipeg", "America/Vancouver"),
        states=_CA_STATES,
    ),
    CountryReference(
        code="GB",
        code_3="GBR",
        name="United Kingdom",
        currency_code="GBP",
        phone_code="+44",
        region="Europe",
        postal_format="@@# #@@",
        latitude_range=(49.9, 58.7),
        longitude_range=(-8.2, 1.8),
        timezones=("Europe/London",),
        states=_GB_STATES,
    ),
    CountryReference(
        code="DE",
        code_3="DEU",
        name="Germany",
        currency_code="EUR",
        phone_code="+49",
        region="Europe",
        postal_format="#####",
        latitude_range=(47.3, 55.1),
        longitude_range=(5.9, 15.0),
        timezones=("Europe/Berlin",),
        states=_DE_STATES,
    ),
    CountryReference(
        code="AU",
        code_3="AUS",
        name="Australia",
        currency_code="AUD",
        phone_code="+61",
        region="Oceania",
        postal_format="####",
        latitude_range=(-43.6, -10.7),
        longitude_range=(113.3, 153.6),
        timezones=("Australia/Sydney", "Australia/Perth", "Australia/Adelaide"),
        states=_AU_STATES,
    ),
    CountryReference(
        code="IN",
        code_3="IND",
        name="India",
        currency_code="INR",
        phone_code="+91",
        region="Asia",
        postal_format="######",
        latitude_range=(8.1, 35.5),
        longitude_range=(68.1, 97.4),
        timezones=("Asia/Kolkata",),
        states=_IN_STATES,
    ),
)

_BY_CODE: dict[str, CountryReference] = {country.code: country for country in COUNTRY_REFERENCE}


def supported_countries() -> tuple[str, ...]:
    """Return the ISO alpha-2 codes with subdivision data available."""
    return tuple(_BY_CODE)


def country_by_code(code: str) -> CountryReference:
    """Look up reference data for a country.

    Args:
        code: ISO 3166-1 alpha-2 code, case-insensitive.

    Returns:
        The country reference entry.

    Raises:
        KeyError: If the country has no reference data.
    """
    try:
        return _BY_CODE[code.upper()]
    except KeyError:
        raise KeyError(
            f"No geography reference data for country {code!r}. "
            f"Supported countries: {supported_countries()}"
        ) from None
