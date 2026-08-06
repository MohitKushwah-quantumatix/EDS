"""The ``eds healthcare`` command group.

Exposes healthcare data generation to the command line. CLI options override
the values loaded from the configuration files, so a demo can be resized
without editing YAML.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated

import polars as pl
import typer

from eds.adapters.parquet.reader import DatasetNotFoundError, read_datasets
from eds.adapters.parquet.writer import ExportError, write_datasets
from eds.core.validation.issues import ValidationError
from eds.domains.healthcare.config import (
    BillingConfig,
    EncounterConfig,
    MasterDataConfig,
    PatientConfig,
    PlatformConfig,
    ProviderConfig,
    SimulationConfig,
    load_config,
)
from eds.domains.healthcare.generators.encounter_data import (
    REQUIRED_MASTER_DATASETS as REQUIRED_ENCOUNTER_DATASETS,
    generate_encounter_data,
)
from eds.domains.healthcare.generators.master_data import (
    MasterData,
    generate_master_data,
)
from eds.domains.healthcare.generators.patient_data import (
    REQUIRED_MASTER_DATASETS as REQUIRED_PATIENT_DATASETS,
    generate_patient_data,
)
from eds.domains.healthcare.generators.provider_data import (
    REQUIRED_MASTER_DATASETS as REQUIRED_PROVIDER_DATASETS,
    generate_provider_data,
)
from eds.domains.healthcare.generators.additional.immunizations import generate_immunizations
from eds.domains.healthcare.generators.additional.patient_emergency_contacts import (
    generate_patient_emergency_contacts,
)
from eds.domains.healthcare.generators.additional.admissions import generate_admissions
from eds.domains.healthcare.generators.additional.discharge_summaries import (
    generate_discharge_summaries,
)
from eds.domains.healthcare.generators.additional.lab_results import generate_lab_results
from eds.domains.healthcare.generators.additional.medication_administration import (
    generate_medication_administration,
)
from eds.domains.healthcare.generators.additional.radiology_reports import (
    generate_radiology_reports,
)
from eds.domains.healthcare.generators.additional.referrals import generate_referrals
from eds.domains.healthcare.validation.billing_validation import validate_billing_data
from eds.domains.healthcare.validation.encounter_validation import validate_encounter_data
from eds.domains.healthcare.validation.master_data import validate_master_data
from eds.domains.healthcare.validation.patient_validation import validate_patient_data
from eds.domains.healthcare.validation.provider_validation import validate_provider_data

__all__ = ["healthcare_app"]

healthcare_app = typer.Typer(
    name="healthcare",
    help="Generate healthcare simulation datasets.",
    no_args_is_help=True,
    add_completion=False,
)

_EXIT_CONFIG_ERROR = 2
_EXIT_VALIDATION_ERROR = 3
_EXIT_EXPORT_ERROR = 4


def _apply_overrides(
    config: SimulationConfig,
    seed: int | None = None,
    departments: int | None = None,
    specialties: int | None = None,
    insurance_plans: int | None = None,
    room_types: int | None = None,
    medications: int | None = None,
    diagnosis_codes: int | None = None,
    procedure_codes: int | None = None,
    billing_codes: int | None = None,
    facilities: int | None = None,
    patients: int | None = None,
    providers: int | None = None,
    output: Path | None = None,
    config_dir: Path | None = None,
) -> SimulationConfig:
    """Apply CLI overrides on top of the loaded configuration."""
    platform_updates: dict[str, object] = {}
    if seed is not None:
        platform_updates["seed"] = seed
    if output is not None:
        platform_updates["output_directory"] = output
    else:
        # Default to a domain-specific subdirectory so retail and healthcare
        # outputs do not share the same folder.
        platform_updates["output_directory"] = config.platform.output_directory / "healthcare"

    master_updates: dict[str, object] = {}
    if departments is not None:
        master_updates["department_count"] = departments
    if specialties is not None:
        master_updates["specialty_count"] = specialties
    if insurance_plans is not None:
        master_updates["insurance_plan_count"] = insurance_plans
    if room_types is not None:
        master_updates["room_type_count"] = room_types
    if medications is not None:
        master_updates["medication_count"] = medications
    if diagnosis_codes is not None:
        master_updates["diagnosis_code_count"] = diagnosis_codes
    if procedure_codes is not None:
        master_updates["procedure_code_count"] = procedure_codes
    if billing_codes is not None:
        master_updates["billing_code_count"] = billing_codes
    if facilities is not None:
        master_updates["facility_count"] = facilities

    patient_updates: dict[str, object] = {}
    if patients is not None:
        patient_updates["patient_count"] = patients

    provider_updates: dict[str, object] = {}
    if providers is not None:
        provider_updates["provider_count"] = providers

    try:
        platform = (
            PlatformConfig.model_validate({**config.platform.model_dump(), **platform_updates})
            if platform_updates
            else config.platform
        )
        master = (
            MasterDataConfig.model_validate({**config.master_data.model_dump(), **master_updates})
            if master_updates
            else config.master_data
        )
        patient = (
            PatientConfig.model_validate({**config.patients.model_dump(), **patient_updates})
            if patient_updates
            else config.patients
        )
        provider = (
            ProviderConfig.model_validate({**config.providers.model_dump(), **provider_updates})
            if provider_updates
            else config.providers
        )
    except ValueError as exc:
        raise typer.Exit(code=_EXIT_CONFIG_ERROR) from exc

    return SimulationConfig(
        platform=platform,
        master_data=master,
        patients=patient,
        providers=provider,
        encounters=config.encounters,
        billing=config.billing,
        evolution=config.evolution,
    )


def _report(datasets: Mapping[str, pl.DataFrame], seed: int, destination: Path) -> None:
    """Print a per-dataset row count summary."""
    counts = {name: frame.height for name, frame in datasets.items()}
    typer.echo(f"Seed: {seed}")
    typer.echo(f"Output: {destination}")
    width = max(len(name) for name in counts)
    for name, count in counts.items():
        typer.echo(f"  {name:<{width}}  {count:>12,} rows")
    typer.echo(f"Total: {sum(counts.values()):,} rows across {len(counts)} datasets")


@healthcare_app.command("master-data")
def healthcare_master_data(
    seed: Annotated[
        int | None, typer.Option("--seed", help="Random seed. Overrides simulation.yaml.")
    ] = None,
    departments: Annotated[
        int | None, typer.Option("--departments", min=1, help="Number of departments.")
    ] = None,
    specialties: Annotated[
        int | None, typer.Option("--specialties", min=1, help="Number of specialties.")
    ] = None,
    insurance_plans: Annotated[
        int | None, typer.Option("--insurance-plans", min=1, help="Number of insurance plans.")
    ] = None,
    room_types: Annotated[
        int | None, typer.Option("--room-types", min=1, help="Number of room types.")
    ] = None,
    medications: Annotated[
        int | None, typer.Option("--medications", min=1, help="Number of medications.")
    ] = None,
    diagnosis_codes: Annotated[
        int | None, typer.Option("--diagnosis-codes", min=1, help="Number of diagnosis codes.")
    ] = None,
    procedure_codes: Annotated[
        int | None, typer.Option("--procedure-codes", min=1, help="Number of procedure codes.")
    ] = None,
    billing_codes: Annotated[
        int | None, typer.Option("--billing-codes", min=1, help="Number of billing codes.")
    ] = None,
    facilities: Annotated[
        int | None, typer.Option("--facilities", min=1, help="Number of facilities.")
    ] = None,
    output: Annotated[
        Path | None, typer.Option("--output", help="Output directory for Parquet files.")
    ] = None,
    config_dir: Annotated[
        Path | None, typer.Option("--config-dir", help="Directory holding the YAML config files.")
    ] = None,
    validate: Annotated[
        bool, typer.Option("--validate/--no-validate", help="Validate before writing.")
    ] = True,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Generate and validate without writing files.")
    ] = False,
) -> None:
    """Generate healthcare master datasets and write them as Parquet."""
    try:
        config = load_config(config_dir)
        config = _apply_overrides(
            config,
            seed=seed,
            departments=departments,
            specialties=specialties,
            insurance_plans=insurance_plans,
            room_types=room_types,
            medications=medications,
            diagnosis_codes=diagnosis_codes,
            procedure_codes=procedure_codes,
            billing_codes=billing_codes,
            facilities=facilities,
            output=output,
        )
    except Exception as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR) from exc

    try:
        data = generate_master_data(config)
    except Exception as exc:
        typer.echo(f"Generation failed: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR) from exc

    if validate:
        issues = validate_master_data(data.datasets)
        if issues:
            typer.echo(f"Validation failed: {len(issues)} issue(s)", err=True)
            raise typer.Exit(code=_EXIT_VALIDATION_ERROR)
        typer.echo("Validation passed.")

    if dry_run:
        typer.echo("Dry run: no files written.")
        _report(data.datasets, data.seed, config.platform.output_directory)
        return

    try:
        write_datasets(data.datasets, config.platform.output_directory)
    except ExportError as exc:
        typer.echo(f"Export failed: {exc}", err=True)
        raise typer.Exit(code=_EXIT_EXPORT_ERROR) from exc

    _report(data.datasets, data.seed, config.platform.output_directory)


@healthcare_app.command("patients")
def healthcare_patients(
    seed: Annotated[
        int | None, typer.Option("--seed", help="Random seed. Overrides simulation.yaml.")
    ] = None,
    patients: Annotated[
        int | None, typer.Option("--patients", min=1, help="Number of patients to generate.")
    ] = None,
    output: Annotated[
        Path | None, typer.Option("--output", help="Output directory for Parquet files.")
    ] = None,
    config_dir: Annotated[
        Path | None, typer.Option("--config-dir", help="Directory holding the YAML config files.")
    ] = None,
    validate: Annotated[
        bool, typer.Option("--validate/--no-validate", help="Validate before writing.")
    ] = True,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Generate and validate without writing files.")
    ] = False,
) -> None:
    """Generate healthcare patient datasets and write them as Parquet."""
    try:
        config = load_config(config_dir)
        config = _apply_overrides(config, seed=seed, patients=patients, output=output)
    except Exception as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR) from exc

    source = config.platform.output_directory
    try:
        master = read_datasets(REQUIRED_PATIENT_DATASETS, source)
    except DatasetNotFoundError as exc:
        typer.echo(f"Master data not found: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR) from exc

    try:
        data = generate_patient_data(config, master)
    except Exception as exc:
        typer.echo(f"Generation failed: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR) from exc

    combined_upstream = {**master, **data.datasets}
    try:
        additional = {
            "immunizations": generate_immunizations(config, combined_upstream),
            "patient_emergency_contacts": generate_patient_emergency_contacts(
                config, combined_upstream
            ),
        }
    except Exception as exc:
        typer.echo(f"Additional generation failed: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR) from exc

    datasets = {**data.datasets, **additional}

    if validate:
        issues = validate_patient_data(
            combined_upstream,
            config.patients.min_addresses,
            config.patients.max_addresses,
        )
        if issues:
            typer.echo(f"Validation failed: {len(issues)} issue(s)", err=True)
            raise typer.Exit(code=_EXIT_VALIDATION_ERROR)
        typer.echo("Validation passed.")

    if dry_run:
        typer.echo("Dry run: no files written.")
        _report(datasets, data.seed, config.platform.output_directory)
        return

    try:
        write_datasets(datasets, config.platform.output_directory)
    except ExportError as exc:
        typer.echo(f"Export failed: {exc}", err=True)
        raise typer.Exit(code=_EXIT_EXPORT_ERROR) from exc

    _report(datasets, data.seed, config.platform.output_directory)


@healthcare_app.command("providers")
def healthcare_providers(
    seed: Annotated[
        int | None, typer.Option("--seed", help="Random seed. Overrides simulation.yaml.")
    ] = None,
    providers: Annotated[
        int | None, typer.Option("--providers", min=1, help="Number of providers to generate.")
    ] = None,
    output: Annotated[
        Path | None, typer.Option("--output", help="Output directory for Parquet files.")
    ] = None,
    config_dir: Annotated[
        Path | None, typer.Option("--config-dir", help="Directory holding the YAML config files.")
    ] = None,
    validate: Annotated[
        bool, typer.Option("--validate/--no-validate", help="Validate before writing.")
    ] = True,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Generate and validate without writing files.")
    ] = False,
) -> None:
    """Generate healthcare provider datasets and write them as Parquet."""
    try:
        config = load_config(config_dir)
        config = _apply_overrides(config, seed=seed, providers=providers, output=output)
    except Exception as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR) from exc

    source = config.platform.output_directory
    try:
        master = read_datasets(REQUIRED_PROVIDER_DATASETS, source)
    except DatasetNotFoundError as exc:
        typer.echo(f"Master data not found: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR) from exc

    try:
        data = generate_provider_data(config, master)
    except Exception as exc:
        typer.echo(f"Generation failed: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR) from exc

    if validate:
        issues = validate_provider_data({**master, **data.datasets})
        if issues:
            typer.echo(f"Validation failed: {len(issues)} issue(s)", err=True)
            raise typer.Exit(code=_EXIT_VALIDATION_ERROR)
        typer.echo("Validation passed.")

    if dry_run:
        typer.echo("Dry run: no files written.")
        _report(data.datasets, data.seed, config.platform.output_directory)
        return

    try:
        write_datasets(data.datasets, config.platform.output_directory)
    except ExportError as exc:
        typer.echo(f"Export failed: {exc}", err=True)
        raise typer.Exit(code=_EXIT_EXPORT_ERROR) from exc

    _report(data.datasets, data.seed, config.platform.output_directory)


@healthcare_app.command("encounters")
def healthcare_encounters(
    seed: Annotated[
        int | None, typer.Option("--seed", help="Random seed. Overrides simulation.yaml.")
    ] = None,
    output: Annotated[
        Path | None, typer.Option("--output", help="Output directory for Parquet files.")
    ] = None,
    config_dir: Annotated[
        Path | None, typer.Option("--config-dir", help="Directory holding the YAML config files.")
    ] = None,
    validate: Annotated[
        bool, typer.Option("--validate/--no-validate", help="Validate before writing.")
    ] = True,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Generate and validate without writing files.")
    ] = False,
) -> None:
    """Generate healthcare encounter and billing datasets and write them as Parquet."""
    try:
        config = load_config(config_dir)
        config = _apply_overrides(config, seed=seed, output=output)
    except Exception as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR) from exc

    source = config.platform.output_directory
    try:
        upstream = read_datasets(REQUIRED_ENCOUNTER_DATASETS, source)
    except DatasetNotFoundError as exc:
        typer.echo(f"Upstream data not found: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR) from exc

    try:
        data = generate_encounter_data(config, upstream)
    except Exception as exc:
        typer.echo(f"Generation failed: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR) from exc

    combined_upstream = {**upstream, **data.datasets}
    try:
        additional = {
            "lab_results": generate_lab_results(config, combined_upstream),
            "radiology_reports": generate_radiology_reports(config, combined_upstream),
            "medication_administration": generate_medication_administration(
                config, combined_upstream
            ),
            "admissions": generate_admissions(config, combined_upstream),
            "discharge_summaries": generate_discharge_summaries(config, combined_upstream),
            "referrals": generate_referrals(config, combined_upstream),
        }
    except Exception as exc:
        typer.echo(f"Additional generation failed: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR) from exc

    datasets = {**data.datasets, **additional}

    if validate:
        issues = validate_encounter_data({**upstream, **data.datasets})
        issues += validate_billing_data({**upstream, **data.datasets})
        if issues:
            typer.echo(f"Validation failed: {len(issues)} issue(s)", err=True)
            raise typer.Exit(code=_EXIT_VALIDATION_ERROR)
        typer.echo("Validation passed.")

    if dry_run:
        typer.echo("Dry run: no files written.")
        _report(datasets, data.seed, config.platform.output_directory)
        return

    try:
        write_datasets(datasets, config.platform.output_directory)
    except ExportError as exc:
        typer.echo(f"Export failed: {exc}", err=True)
        raise typer.Exit(code=_EXIT_EXPORT_ERROR) from exc

    _report(datasets, data.seed, config.platform.output_directory)

