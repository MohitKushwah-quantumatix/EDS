"""Generate all master data datasets."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import polars as pl

from eds.config import SimulationConfig
from eds.core.random_streams import make_rng, resolve_seed
from eds.domains.healthcare.domain.master_data import MASTER_DATA_DATASETS
from eds.domains.healthcare.generators.reference import (
    DEPARTMENTS,
    SPECIALTIES,
    INSURANCE_PLANS,
    ROOM_TYPES,
    MEDICATION_FORMS,
    DIAGNOSIS_CODES,
    PROCEDURE_CODES,
    COUNTRIES,
    STATES,
    CITIES,
)

__all__ = ["MasterData", "generate_master_data"]


@dataclass(frozen=True, slots=True)
class MasterData:
    """The complete set of generated master data datasets."""

    datasets: Mapping[str, pl.DataFrame]
    seed: int

    def __getitem__(self, name: str) -> pl.DataFrame:
        try:
            return self.datasets[name]
        except KeyError:
            raise KeyError(
                f"Unknown dataset {name!r}. Generated: {sorted(self.datasets)}"
            ) from None

    def __iter__(self):
        return iter(self.datasets.items())


def generate_master_data(config: SimulationConfig) -> MasterData:
    """Generate all master data datasets."""
    seed = resolve_seed(config.platform.seed)
    rng = make_rng(seed, "master_data")

    departments = pl.DataFrame([{
        "department_id": i,
        "department_code": f"DEPT-{i:03d}",
        "department_name": dept,
        "description": dept,
    } for i, dept in enumerate(DEPARTMENTS[:config.master_data.department_count], 1)])

    specialties = pl.DataFrame([{
        "specialty_id": i,
        "specialty_code": f"SPEC-{i:03d}",
        "specialty_name": spec,
        "description": spec,
    } for i, spec in enumerate(SPECIALTIES[:config.master_data.specialty_count], 1)])

    insurance_plans = pl.DataFrame([{
        "insurance_plan_id": i,
        "plan_name": plan,
        "plan_type": "HEALTH",
        "coverage_tier": "TIER_1",
        "premium_amount": round(rng.uniform(1000.0, 50000.0), 2),
        "currency_code": "INR",
    } for i, plan in enumerate(INSURANCE_PLANS[:config.master_data.insurance_plan_count], 1)])

    room_types = pl.DataFrame([{
        "room_type_id": i,
        "room_type_code": f"RM-{i:03d}",
        "room_type_name": rt,
        "base_rate": round(rng.uniform(500.0, 5000.0), 2),
        "currency_code": "INR",
    } for i, rt in enumerate(ROOM_TYPES[:config.master_data.room_type_count], 1)])

    medications = pl.DataFrame([{
        "medication_id": i,
        "medication_code": f"MED-{i:05d}",
        "medication_name": f"Medication {i}",
        "form": rng.choice(MEDICATION_FORMS),
        "strength": f"{rng.choice([10, 20, 50, 100, 250, 500])}mg",
        "unit_of_measure": "UNIT",
    } for i in range(1, config.master_data.medication_count + 1)])

    diagnosis_codes = pl.DataFrame([{
        "diagnosis_code_id": i,
        "code": f"ICD10-{i:05d}",
        "description": f"Diagnosis code {i}",
        "category": rng.choice(["INFECTIOUS", "NEOPLASMS", "BLOOD", "ENDOCRINE", "MENTAL", "NERVOUS", "EYE", "EAR", "CIRCULATORY", "RESPIRATORY"]),
    } for i in range(1, config.master_data.diagnosis_code_count + 1)])

    procedure_codes = pl.DataFrame([{
        "procedure_code_id": i,
        "code": f"CPT-{i:05d}",
        "description": f"Procedure code {i}",
        "category": rng.choice(["EVALUATION", "SURGERY", "RADIOLOGY", "LABORATORY", "PATHOLOGY"]),
    } for i in range(1, config.master_data.procedure_code_count + 1)])

    billing_codes = pl.DataFrame([{
        "billing_code_id": i,
        "code": f"BILL-{i:05d}",
        "description": f"Billing code {i}",
        "charge_amount": round(rng.uniform(100.0, 50000.0), 2),
        "currency_code": "INR",
    } for i in range(1, config.master_data.billing_code_count + 1)])

    facilities = pl.DataFrame([{
        "facility_id": i,
        "facility_code": f"FAC-{i:03d}",
        "facility_name": f"Hospital {i}",
        "facility_type": "HOSPITAL",
    } for i in range(1, config.master_data.facility_count + 1)])

    # Geography datasets
    countries = pl.DataFrame([{
        "country_id": i,
        "country_code": country["code"],
        "country_name": country["name"],
    } for i, country in enumerate(COUNTRIES, 1)])

    states = pl.DataFrame([{
        "state_id": i,
        "state_code": state["code"],
        "state_name": state["name"],
        "country_id": 1,
    } for i, state in enumerate(STATES, 1)])

    cities = pl.DataFrame([{
        "city_id": i,
        "city_code": city["code"],
        "city_name": city["name"],
        "state_id": next((j + 1 for j, s in enumerate(STATES) if s["code"] == city["state_code"]), 1),
    } for i, city in enumerate(CITIES, 1)])

    datasets = {
        "countries": countries,
        "states": states,
        "cities": cities,
        "departments": departments,
        "specialties": specialties,
        "insurance_plans": insurance_plans,
        "room_types": room_types,
        "medications": medications,
        "diagnosis_codes": diagnosis_codes,
        "procedure_codes": procedure_codes,
        "billing_codes": billing_codes,
        "facilities": facilities,
    }

    ordered = {dataset.name: datasets[dataset.name] for dataset in MASTER_DATA_DATASETS if dataset.name in datasets}
    return MasterData(datasets=ordered, seed=seed)
