"""The Healthcare domain's self-description."""

from __future__ import annotations

from eds.platform.domain import DomainStage, register_domain

__all__ = ["HEALTHCARE_DOMAIN_NAME", "HealthcareDomain"]

HEALTHCARE_DOMAIN_NAME = "healthcare"


def _master_data_stage() -> DomainStage:
    from eds.domains.healthcare.domain.master_data import dataset_names
    return DomainStage(name="master-data", requires=(), produces=dataset_names())


def _patients_stage() -> DomainStage:
    from eds.domains.healthcare.generators.patient_data import REQUIRED_MASTER_DATASETS
    from eds.domains.healthcare.domain.patient.schema import patient_dataset_names
    produces = (
        *patient_dataset_names(),
        "immunizations",
        "patient_emergency_contacts",
    )
    requires = dict.fromkeys(REQUIRED_MASTER_DATASETS)
    return DomainStage(
        name="patients",
        requires=tuple(name for name in requires if name not in set(produces)),
        produces=produces,
    )


def _providers_stage() -> DomainStage:
    from eds.domains.healthcare.generators.provider_data import REQUIRED_MASTER_DATASETS
    from eds.domains.healthcare.domain.provider.schema import provider_dataset_names
    return DomainStage(
        name="providers",
        requires=REQUIRED_MASTER_DATASETS,
        produces=provider_dataset_names(),
    )


def _encounters_stage() -> DomainStage:
    from eds.domains.healthcare.generators.encounter_data import REQUIRED_MASTER_DATASETS
    from eds.domains.healthcare.domain.encounter.schema import encounter_dataset_names
    from eds.domains.healthcare.domain.billing.schema import billing_dataset_names
    produces = (
        *encounter_dataset_names(),
        *billing_dataset_names(),
        "lab_results",
        "radiology_reports",
        "medication_administration",
        "admissions",
        "discharge_summaries",
        "referrals",
    )
    requires = dict.fromkeys(REQUIRED_MASTER_DATASETS)
    return DomainStage(
        name="encounters",
        requires=tuple(name for name in requires if name not in set(produces)),
        produces=produces,
    )


class HealthcareDomain:
    """The Healthcare simulation domain, described for the platform."""

    @property
    def name(self) -> str:
        return HEALTHCARE_DOMAIN_NAME

    @property
    def stages(self):
        return (
            _master_data_stage(),
            _patients_stage(),
            _providers_stage(),
            _encounters_stage(),
        )

    @property
    def dataset_names(self):
        return tuple(name for stage in self.stages for name in stage.produces)


register_domain(HealthcareDomain())
