"""Curated healthcare reference data."""

from __future__ import annotations

__all__ = [
    "DEPARTMENTS",
    "SPECIALTIES",
    "INSURANCE_PLANS",
    "ROOM_TYPES",
    "MEDICATION_FORMS",
    "DIAGNOSIS_CODES",
    "PROCEDURE_CODES",
    "COUNTRIES",
    "STATES",
    "CITIES",
]

DEPARTMENTS: tuple[str, ...] = (
    "CARDIOLOGY",
    "ONCOLOGY",
    "NEUROLOGY",
    "ORTHOPEDICS",
    "PEDIATRICS",
    "DERMATOLOGY",
    "PSYCHIATRY",
    "RADIOLOGY",
    "EMERGENCY",
    "SURGERY",
    "INTERNAL_MEDICINE",
    "OBSTETRICS",
    "GYNECOLOGY",
    "UROLOGY",
    "ENT",
    "OPHTHALMOLOGY",
    "ANESTHESIOLOGY",
    "PATHOLOGY",
    "LABORATORY",
    "PHARMACY",
)

SPECIALTIES: tuple[str, ...] = DEPARTMENTS

INSURANCE_PLANS: tuple[str, ...] = (
    "STAR_HEALTH",
    "HDFC_ERGO",
    "ICICI_PRUDENTIAL",
    "BAJAJ_ALLIANZ",
    "NEW_INDIA_ASSURANCE",
    "UNITED_INDIA",
    "SELF_PAY",
)

ROOM_TYPES: tuple[str, ...] = (
    "ICU",
    "GENERAL",
    "PRIVATE",
    "SEMI_PRIVATE",
    "EMERGENCY",
)

MEDICATION_FORMS: tuple[str, ...] = (
    "TABLET",
    "CAPSULE",
    "INJECTION",
    "TOPICAL",
    "INHALER",
    "LIQUID",
    "PATCH",
    "DROPS",
    "SUPPOSITORY",
    "INTRAVENOUS",
)

DIAGNOSIS_CODES: tuple[str, ...] = (
    "A00-B99: Infectious diseases",
    "C00-D49: Neoplasms",
    "D50-D89: Blood diseases",
    "E00-E89: Endocrine diseases",
    "F01-F99: Mental disorders",
    "G00-G99: Nervous system diseases",
    "H00-H59: Eye diseases",
    "H60-H95: Ear diseases",
    "I00-I99: Circulatory system diseases",
    "J00-J99: Respiratory system diseases",
)

PROCEDURE_CODES: tuple[str, ...] = (
    "99201-99215: Office visits",
    "99221-99239: Hospital visits",
    "99281-99288: Emergency visits",
    "99304-99318: Nursing facility visits",
    "99324-99350: Home visits",
)

# Indian geography reference data
COUNTRIES: tuple[dict[str, str], ...] = (
    {"code": "IN", "name": "India"},
)

STATES: tuple[dict[str, str], ...] = (
    {"code": "MH", "name": "Maharashtra"},
    {"code": "DL", "name": "Delhi"},
    {"code": "KA", "name": "Karnataka"},
    {"code": "TN", "name": "Tamil Nadu"},
    {"code": "GJ", "name": "Gujarat"},
    {"code": "RJ", "name": "Rajasthan"},
    {"code": "UP", "name": "Uttar Pradesh"},
    {"code": "WB", "name": "West Bengal"},
    {"code": "KL", "name": "Kerala"},
    {"code": "TS", "name": "Telangana"},
)

CITIES: tuple[dict[str, str], ...] = (
    {"code": "BOM", "name": "Mumbai", "state_code": "MH"},
    {"code": "DEL", "name": "New Delhi", "state_code": "DL"},
    {"code": "BLR", "name": "Bangalore", "state_code": "KA"},
    {"code": "MAA", "name": "Chennai", "state_code": "TN"},
    {"code": "AHM", "name": "Ahmedabad", "state_code": "GJ"},
    {"code": "JAI", "name": "Jaipur", "state_code": "RJ"},
    {"code": "LUC", "name": "Lucknow", "state_code": "UP"},
    {"code": "KOL", "name": "Kolkata", "state_code": "WB"},
    {"code": "COC", "name": "Kochi", "state_code": "KL"},
    {"code": "HYD", "name": "Hyderabad", "state_code": "TS"},
)
