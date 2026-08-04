"""What each Healthcare dataset does when a day passes."""

from __future__ import annotations

from enum import StrEnum

from eds.domains.healthcare.domain.master_data import MASTER_DATA_DATASETS

__all__ = ["Temporality", "DATASET_TEMPORALITY"]


class Temporality(StrEnum):
    """How a dataset behaves over time."""

    APPEND_ONLY = "APPEND_ONLY"
    MUTABLE_SNAPSHOT = "MUTABLE_SNAPSHOT"
    SLOWLY_CHANGING = "SLOWLY_CHANGING"
    STATIC = "STATIC"


DATASET_TEMPORALITY: dict[str, Temporality] = {
    # Geography datasets: static
    "countries": Temporality.STATIC,
    "states": Temporality.STATIC,
    "cities": Temporality.STATIC,
    # Master data: mostly static, some slowly changing
    "departments": Temporality.STATIC,
    "specialties": Temporality.STATIC,
    "insurance_plans": Temporality.STATIC,
    "room_types": Temporality.STATIC,
    "medications": Temporality.STATIC,
    "diagnosis_codes": Temporality.STATIC,
    "procedure_codes": Temporality.STATIC,
    "billing_codes": Temporality.STATIC,
    "facilities": Temporality.STATIC,
    # Patient datasets
    "patients": Temporality.SLOWLY_CHANGING,
    "patient_addresses": Temporality.MUTABLE_SNAPSHOT,
    "patient_insurance": Temporality.MUTABLE_SNAPSHOT,
    "patient_allergies": Temporality.MUTABLE_SNAPSHOT,
    # Provider datasets
    "providers": Temporality.SLOWLY_CHANGING,
    "provider_departments": Temporality.MUTABLE_SNAPSHOT,
    "provider_specialties": Temporality.SLOWLY_CHANGING,
    # Encounter datasets: append only
    "encounters": Temporality.APPEND_ONLY,
    "appointments": Temporality.APPEND_ONLY,
    "vitals": Temporality.APPEND_ONLY,
    "medications_prescribed": Temporality.APPEND_ONLY,
    "diagnoses": Temporality.APPEND_ONLY,
    "procedures": Temporality.APPEND_ONLY,
    # Billing datasets: append only
    "billing": Temporality.APPEND_ONLY,
    "claims": Temporality.APPEND_ONLY,
}


def temporality_of(name: str) -> Temporality:
    """Return the temporality of a dataset."""
    try:
        return DATASET_TEMPORALITY[name]
    except KeyError:
        raise KeyError(
            f"Dataset {name!r} has not declared how it behaves over time."
        ) from None
