"""Business configuration for the Healthcare domain."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from eds.core.config import (
    DEFAULT_CONFIG_DIR,
    ConfigError,
    build_model,
    read_yaml_mapping,
)
from eds.platform.config import PlatformConfig, load_platform_config

__all__ = [
    "MasterDataConfig",
    "PatientConfig",
    "ProviderConfig",
    "EncounterConfig",
    "BillingConfig",
    "EvolutionConfig",
    "SimulationConfig",
    "load_config",
]

MASTER_DATA_CONFIG_FILE: Final[str] = "healthcare_master_data.yaml"
PATIENT_CONFIG_FILE: Final[str] = "healthcare_patients.yaml"
PROVIDER_CONFIG_FILE: Final[str] = "healthcare_providers.yaml"
ENCOUNTER_CONFIG_FILE: Final[str] = "healthcare_encounters.yaml"
BILLING_CONFIG_FILE: Final[str] = "healthcare_billing.yaml"
EVOLUTION_CONFIG_FILE: Final[str] = "healthcare_evolution.yaml"


class MasterDataConfig(BaseModel):
    """Business configuration for the F001 master data generator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    department_count: int = Field(default=10, ge=1)
    specialty_count: int = Field(default=10, ge=1)
    insurance_plan_count: int = Field(default=6, ge=1)
    room_type_count: int = Field(default=5, ge=1)
    medication_count: int = Field(default=50, ge=1)
    diagnosis_code_count: int = Field(default=20, ge=1)
    procedure_code_count: int = Field(default=20, ge=1)
    billing_code_count: int = Field(default=15, ge=1)
    facility_count: int = Field(default=3, ge=1)
    batch_size: int = Field(default=100_000, ge=1)


class PatientConfig(BaseModel):
    """Business configuration for the F002 patient generator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    patient_count: int = Field(default=1000, ge=1)
    min_addresses: int = Field(default=1, ge=1)
    max_addresses: int = Field(default=2, ge=1)
    registration_years: int = Field(default=5, ge=1, le=50)
    reference_date: date = date(2026, 1, 1)
    batch_size: int = Field(default=100_000, ge=1)

    @model_validator(mode="after")
    def _check_address_bounds(self) -> PatientConfig:
        if self.min_addresses > self.max_addresses:
            raise ValueError(
                f"min_addresses ({self.min_addresses}) cannot exceed max_addresses ({self.max_addresses})"
            )
        return self


class ProviderConfig(BaseModel):
    """Business configuration for the F003 provider generator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_count: int = Field(default=50, ge=1)
    min_specialties: int = Field(default=1, ge=1)
    max_specialties: int = Field(default=3, ge=1)
    department_count: int = Field(default=10, ge=1)
    reference_date: date = date(2026, 1, 1)
    batch_size: int = Field(default=100_000, ge=1)

    @model_validator(mode="after")
    def _check_specialty_bounds(self) -> ProviderConfig:
        if self.min_specialties > self.max_specialties:
            raise ValueError(
                f"min_specialties ({self.min_specialties}) cannot exceed max_specialties ({self.max_specialties})"
            )
        return self


class EncounterConfig(BaseModel):
    """Business configuration for the F004-F010 encounter and billing generators."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    daily_encounter_rate: float = Field(default=0.1, ge=0.0, le=1.0)
    inpatient_rate: float = Field(default=0.3, ge=0.0, le=1.0)
    appointment_rate: float = Field(default=0.8, ge=0.0, le=1.0)
    min_encounter_duration: int = Field(default=15, ge=1)
    max_encounter_duration: int = Field(default=120, ge=1)
    reference_date: date = date(2026, 1, 1)
    batch_size: int = Field(default=100_000, ge=1)

    @model_validator(mode="after")
    def _check_duration_bounds(self) -> EncounterConfig:
        if self.min_encounter_duration > self.max_encounter_duration:
            raise ValueError(
                f"min_encounter_duration ({self.min_encounter_duration}) cannot exceed max_encounter_duration ({self.max_encounter_duration})"
            )
        return self


class BillingConfig(BaseModel):
    """Business configuration for the F006-F010 billing generators."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    billing_rate: float = Field(default=0.7, ge=0.0, le=1.0)
    claim_rate: float = Field(default=0.8, ge=0.0, le=1.0)
    min_bill_amount: float = Field(default=100.0, ge=0.0)
    max_bill_amount: float = Field(default=50000.0, ge=0.0)
    reference_date: date = date(2026, 1, 1)
    batch_size: int = Field(default=100_000, ge=1)

    @model_validator(mode="after")
    def _check_amount_bounds(self) -> BillingConfig:
        if self.min_bill_amount > self.max_bill_amount:
            raise ValueError(
                f"min_bill_amount ({self.min_bill_amount}) cannot exceed max_bill_amount ({self.max_bill_amount})"
            )
        return self


class EvolutionConfig(BaseModel):
    """How much business happens on one simulated Healthcare day."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    new_patients_per_day: int = Field(default=5, ge=0)
    active_patient_rate: float = Field(default=0.02, ge=0.0, le=1.0)
    max_daily_encounters: int = Field(default=10, ge=1)
    loyalty_points_per_unit: float = Field(default=1.0, ge=0.0)


class SimulationConfig(BaseModel):
    """The complete configuration for a Healthcare simulation run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    platform: PlatformConfig = PlatformConfig()
    master_data: MasterDataConfig = MasterDataConfig()
    patients: PatientConfig = PatientConfig()
    providers: ProviderConfig = ProviderConfig()
    encounters: EncounterConfig = EncounterConfig()
    billing: BillingConfig = BillingConfig()
    evolution: EvolutionConfig = EvolutionConfig()


def load_master_data_config(config_dir: Path | None = None) -> MasterDataConfig:
    path = (config_dir or DEFAULT_CONFIG_DIR) / MASTER_DATA_CONFIG_FILE
    return build_model(MasterDataConfig, read_yaml_mapping(path), path)


def load_patient_config(config_dir: Path | None = None) -> PatientConfig:
    path = (config_dir or DEFAULT_CONFIG_DIR) / PATIENT_CONFIG_FILE
    return build_model(PatientConfig, read_yaml_mapping(path), path)


def load_provider_config(config_dir: Path | None = None) -> ProviderConfig:
    path = (config_dir or DEFAULT_CONFIG_DIR) / PROVIDER_CONFIG_FILE
    return build_model(ProviderConfig, read_yaml_mapping(path), path)


def load_encounter_config(config_dir: Path | None = None) -> EncounterConfig:
    path = (config_dir or DEFAULT_CONFIG_DIR) / ENCOUNTER_CONFIG_FILE
    return build_model(EncounterConfig, read_yaml_mapping(path), path)


def load_billing_config(config_dir: Path | None = None) -> BillingConfig:
    path = (config_dir or DEFAULT_CONFIG_DIR) / BILLING_CONFIG_FILE
    return build_model(BillingConfig, read_yaml_mapping(path), path)


def load_evolution_config(config_dir: Path | None = None) -> EvolutionConfig:
    path = (config_dir or DEFAULT_CONFIG_DIR) / EVOLUTION_CONFIG_FILE
    if not path.is_file():
        return EvolutionConfig()
    return build_model(EvolutionConfig, read_yaml_mapping(path), path)


def load_config(config_dir: Path | None = None) -> SimulationConfig:
    return SimulationConfig(
        platform=load_platform_config(config_dir),
        master_data=load_master_data_config(config_dir),
        patients=load_patient_config(config_dir),
        providers=load_provider_config(config_dir),
        encounters=load_encounter_config(config_dir),
        billing=load_billing_config(config_dir),
        evolution=load_evolution_config(config_dir),
    )
