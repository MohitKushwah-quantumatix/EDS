"""Tests asserting the platform architecture stays intact.

These guard the layering itself rather than any behaviour: the dependency
direction between core, platform, domains and adapters, and the backward
compatibility of every pre-platform import path.

They are deliberately structural. A rule that is only written down in an ADR
drifts; a rule with a test does not.
"""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path

import polars as pl
import pytest

import eds
from eds.adapters.base import AdapterError, DatasetReader, DatasetWriter, WriteResult
from eds.adapters.parquet.adapter import ParquetAdapter
from eds.platform.domain import (
    DomainStage,
    SimulationDomain,
    available_domains,
    get_domain,
    list_domains,
    register_domain,
    resolve_domain,
)
from eds.platform.metadata import PLATFORM_NAME, platform_metadata
from eds.platform.project import create_project

PACKAGE_ROOT = Path(eds.__file__).parent

PLATFORM_PACKAGES: tuple[str, ...] = (
    "eds.core",
    "eds.core.validation",
    "eds.platform",
    "eds.platform.execution",
    "eds.platform.project",
    "eds.domains",
    "eds.domains.retail",
    "eds.adapters",
    "eds.adapters.parquet",
)

#: Which layers each layer is forbidden from importing. Core sits at the
#: bottom; adapters and domains are siblings that must not know about each
#: other; the platform knows about neither.
FORBIDDEN_IMPORTS: dict[str, tuple[str, ...]] = {
    "core": ("eds.domains", "eds.adapters", "eds.platform"),
    "platform": ("eds.domains", "eds.adapters"),
    "adapters": ("eds.domains",),
    "domains": ("eds.adapters",),
}


def imported_modules(path: Path) -> set[str]:
    """Return every ``eds.*`` module a source file imports.

    Args:
        path: Python source file to scan.

    Returns:
        The dotted module names imported from within the package.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("eds"):
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names if alias.name.startswith("eds"))
    return found


# --------------------------------------------------------------------------
# Package layout
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", PLATFORM_PACKAGES)
def test_platform_package_is_importable(name: str) -> None:
    """Every declared platform package imports without side effects."""
    assert importlib.import_module(name) is not None


@pytest.mark.parametrize("name", PLATFORM_PACKAGES)
def test_platform_package_has_a_module_docstring(name: str) -> None:
    """Every declared platform package documents its purpose."""
    module = importlib.import_module(name)

    assert module.__doc__ is not None
    assert module.__doc__.strip()


# --------------------------------------------------------------------------
# Dependency direction
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("layer", "forbidden"), sorted(FORBIDDEN_IMPORTS.items()))
def test_layer_respects_the_dependency_direction(layer: str, forbidden: tuple[str, ...]) -> None:
    """No layer imports one it is not allowed to know about."""
    offenders: list[str] = []
    for source in (PACKAGE_ROOT / layer).rglob("*.py"):
        for module in imported_modules(source):
            if module.startswith(forbidden):
                offenders.append(f"{source.relative_to(PACKAGE_ROOT)} imports {module}")

    assert not offenders, f"{layer} violates the dependency direction: {offenders}"


def test_no_domain_generator_knows_about_an_output_format() -> None:
    """PADR-003: business generators never reference a storage technology."""
    banned = ("parquet", "sql", "mongo", "postgres", "kafka", "delta")
    offenders: list[str] = []
    for source in (PACKAGE_ROOT / "domains").rglob("*.py"):
        lowered = source.read_text(encoding="utf-8").lower()
        for token in banned:
            # `.parquet` appears in dataset file names, which is a naming
            # convention rather than a storage dependency; an *import* is not.
            if f"import {token}" in lowered or f"eds.adapters.{token}" in lowered:
                offenders.append(f"{source.relative_to(PACKAGE_ROOT)} references {token}")

    assert not offenders, offenders


def test_core_is_self_contained() -> None:
    """Core imports nothing from the package but itself."""
    for source in (PACKAGE_ROOT / "core").rglob("*.py"):
        for module in imported_modules(source):
            assert module.startswith("eds.core") or module == "eds.version", (
                f"{source.name} imports {module}"
            )


# --------------------------------------------------------------------------
# Backward compatibility
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("eds.domain.schema", "eds.core.schema"),
        ("eds.generators.frames", "eds.core.frames"),
        ("eds.generators.random_streams", "eds.core.random_streams"),
        ("eds.validation.issues", "eds.core.validation.issues"),
        ("eds.exporters.parquet.writer", "eds.adapters.parquet.writer"),
        ("eds.exporters.parquet.reader", "eds.adapters.parquet.reader"),
        ("eds.domain.master_data", "eds.domains.retail.domain.master_data"),
        ("eds.generators.master_data", "eds.domains.retail.generators.master_data"),
        (
            "eds.generators.commerce.orders",
            "eds.domains.retail.generators.commerce.orders",
        ),
        (
            "eds.validation.order_validation",
            "eds.domains.retail.validation.order_validation",
        ),
    ],
)
def test_old_import_path_yields_the_same_objects(old: str, new: str) -> None:
    """PADR-005: a pre-platform import resolves to the identical objects.

    The contract is every name the new module *defines*, plus everything it
    declares in ``__all__``. Names it merely imports for its own use - ``Path``,
    ``pl`` - are not part of anyone's public surface and are not re-exported.
    """
    legacy = importlib.import_module(old)
    current = importlib.import_module(new)

    defined = {
        name
        for name, value in inspect.getmembers(current)
        if not name.startswith("_") and getattr(value, "__module__", None) == new
    }
    exported = set(getattr(current, "__all__", ()))

    surface = defined | exported
    assert surface, f"{new} exposes no public names"
    for name in sorted(surface):
        assert hasattr(legacy, name), f"{old} lost {name}"
        assert getattr(legacy, name) is getattr(current, name), (
            f"{old}.{name} is a different object"
        )


def test_the_flat_config_module_still_exposes_both_halves() -> None:
    """`eds.config` re-exports the platform and retail halves alike."""
    import eds.config as legacy
    from eds.core.config import ConfigError
    from eds.domains.retail.config import SimulationConfig, load_config
    from eds.platform.config import PlatformConfig

    assert legacy.ConfigError is ConfigError
    assert legacy.PlatformConfig is PlatformConfig
    assert legacy.SimulationConfig is SimulationConfig
    assert legacy.load_config is load_config


def test_the_default_config_directory_survived_the_move() -> None:
    """The configs directory is resolved from the package, not the caller."""
    from eds.core.config import DEFAULT_CONFIG_DIR

    assert DEFAULT_CONFIG_DIR.is_dir()
    assert (DEFAULT_CONFIG_DIR / "simulation.yaml").is_file()


# --------------------------------------------------------------------------
# Platform
# --------------------------------------------------------------------------


def test_platform_metadata_reports_the_running_platform() -> None:
    """Metadata names the platform and carries a contract version."""
    metadata = platform_metadata()

    assert metadata.name == PLATFORM_NAME
    assert metadata.version
    assert metadata.contract_version >= 1


def test_a_project_carries_its_identity(tmp_path: Path) -> None:
    """A project names a domain, a seed and a destination.

    P001 declared ``Project`` as a placeholder value object with no consumer.
    P003 gave it one and replaced it with a durable handle, which is what
    PADR-007 deferred until something needed it. The identity this test cared
    about is now on the manifest; the assertions are unchanged in substance.
    """
    project = create_project(tmp_path / "demo", name="demo", domain="retail", seed=42)

    assert project.domain_name == "retail"
    assert project.seed == 42
    assert project.platform.name == PLATFORM_NAME


@pytest.mark.parametrize(("name", "domain"), [("", "retail"), ("demo", "  ")])
def test_an_unidentifiable_project_is_rejected(tmp_path: Path, name: str, domain: str) -> None:
    """A project without a name or a domain cannot be routed."""
    with pytest.raises(ValueError, match="must not be empty"):
        create_project(tmp_path / "demo", name=name, domain=domain)


class _StubDomain:
    """A minimal conforming domain, used to exercise the registry."""

    def __init__(self, name: str) -> None:
        """Name the stub so each test can register its own.

        Args:
            name: Registry name to claim.
        """
        self._name = name

    @property
    def name(self) -> str:
        """Return the stub's registry name."""
        return self._name

    @property
    def stages(self) -> tuple[DomainStage, ...]:
        """Return a single trivial stage."""
        return (DomainStage(name="things", requires=(), produces=("things",)),)

    @property
    def dataset_names(self) -> tuple[str, ...]:
        """Return every dataset the stub produces."""
        return ("things",)


def test_a_domain_can_register_and_resolve() -> None:
    """The registry is the extension point a second domain plugs into."""
    domain = _StubDomain("stub-resolve")
    register_domain(domain)

    assert "stub-resolve" in list_domains()
    assert get_domain("stub-resolve") is domain
    assert isinstance(domain, SimulationDomain)


def test_registering_the_same_domain_twice_is_harmless() -> None:
    """A domain package that registers on import may be imported repeatedly."""
    domain = _StubDomain("stub-idempotent")
    register_domain(domain)
    register_domain(domain)

    assert get_domain("stub-idempotent") is domain


def test_a_conflicting_domain_registration_is_rejected() -> None:
    """Two different domains cannot claim one name."""
    register_domain(_StubDomain("stub-conflict"))

    with pytest.raises(ValueError, match="already registered"):
        register_domain(_StubDomain("stub-conflict"))


def test_an_unnamed_domain_is_rejected() -> None:
    """A domain that cannot be looked up cannot be registered."""
    with pytest.raises(ValueError, match="non-empty name"):
        register_domain(_StubDomain("   "))


def test_an_unknown_domain_lookup_raises() -> None:
    """Resolving an unregistered domain fails with a helpful message."""
    with pytest.raises(KeyError, match="Unknown domain"):
        get_domain("healthcare")


def test_the_p001_registry_spellings_still_work() -> None:
    """PADR-005: the P001 names are aliases, not removals."""
    assert resolve_domain is get_domain
    assert available_domains is list_domains


@pytest.mark.parametrize("name", ["eds.platform.state"])
def test_the_placeholders_carry_no_implementation(name: str) -> None:
    """What is left of P001's declared-but-empty modules is still empty.

    ``eds.platform.clock`` was one of them until P004, which superseded it with
    the :mod:`eds.platform.time` package (PADR-010) - the same pattern by which
    P003 superseded ``eds.platform.project``. Placeholders are cheap to declare
    and cheap to replace; what they must not do is quietly acquire an
    implementation while still claiming to have none.
    """
    module = importlib.import_module(name)

    assert module.__all__ == []
    assert module.__doc__ is not None
    assert "not implemented" in module.__doc__.lower()


# --------------------------------------------------------------------------
# The Retail domain, as a concrete implementation of the protocol
# --------------------------------------------------------------------------


def test_importing_retail_registers_it() -> None:
    """The domain announces itself; the platform keeps no list of domains."""
    import eds.domains.retail  # noqa: F401

    assert "retail" in list_domains()
    assert isinstance(get_domain("retail"), SimulationDomain)


def test_the_platform_names_no_domain() -> None:
    """PADR-002: adding a domain must not mean editing platform code.

    Only executable code is checked. Docstrings may of course discuss Retail -
    what must not exist is a platform module that carries a domain name as a
    value, because that is the hardcoded registry PADR-002 rules out.
    """
    for source in (PACKAGE_ROOT / "platform").rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        docstrings = {
            id(node.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in docstrings:
                    continue
                assert "retail" not in node.value.lower(), (
                    f"{source.name} carries a domain name as a value"
                )


def test_retail_declares_the_four_cli_stages() -> None:
    """The described pipeline is the one the CLI actually exposes."""
    stages = get_domain("retail").stages

    assert [stage.name for stage in stages] == [
        "master-data",
        "customers",
        "journey",
        "commerce",
    ]


def test_retail_declares_every_dataset_the_pipeline_writes() -> None:
    """The description covers all 39 datasets, each exactly once.

    This is the invariant that keeps the descriptor honest: a feature that adds
    a dataset without declaring it changes this count.
    """
    names = get_domain("retail").dataset_names

    assert len(names) == 39
    assert len(set(names)) == 39


def test_retail_stages_form_a_valid_dependency_order() -> None:
    """Every stage's inputs are produced by a stage before it.

    A scheduler consuming this description needs exactly this property, so it
    is asserted rather than assumed.
    """
    produced: set[str] = set()
    for stage in get_domain("retail").stages:
        missing = set(stage.requires) - produced
        assert not missing, f"{stage.name} requires {sorted(missing)} that nothing produced yet"
        produced.update(stage.produces)


def test_retail_stage_inputs_match_the_generator_declarations() -> None:
    """The descriptor is derived from the generators, not written beside them."""
    from eds.domains.retail.generators.customer_data import REQUIRED_MASTER_DATASETS

    customers = next(s for s in get_domain("retail").stages if s.name == "customers")

    assert customers.requires == REQUIRED_MASTER_DATASETS


def test_retail_master_stage_needs_nothing() -> None:
    """The first stage is the root of the dependency graph."""
    master = get_domain("retail").stages[0]

    assert master.requires == ()
    assert "products" in master.produces


@pytest.mark.parametrize(
    ("name", "requires", "produces"),
    [
        ("", (), ("x",)),
        ("stage", (), ()),
        ("stage", ("x",), ("x",)),
    ],
)
def test_an_incoherent_stage_is_rejected(
    name: str, requires: tuple[str, ...], produces: tuple[str, ...]
) -> None:
    """A stage that is unnamed, empty, or self-referential cannot be scheduled."""
    with pytest.raises(ValueError):
        DomainStage(name=name, requires=requires, produces=produces)


# --------------------------------------------------------------------------
# Adapters
# --------------------------------------------------------------------------


def test_the_parquet_adapter_satisfies_both_protocols(tmp_path: Path) -> None:
    """The one shipped adapter conforms to the declared extension points."""
    adapter = ParquetAdapter(tmp_path)

    assert isinstance(adapter, DatasetWriter)
    assert isinstance(adapter, DatasetReader)
    assert adapter.name == "parquet"
    assert adapter.directory == tmp_path


def test_the_adapter_contract_mentions_no_storage_mechanics() -> None:
    """PADR-003: the protocol describes intent, not a file system.

    The destination is bound at construction, so neither protocol method may
    take or return a path.
    """
    for protocol, method in ((DatasetWriter, "write"), (DatasetReader, "read")):
        rendered = str(inspect.signature(getattr(protocol, method)))
        assert "Path" not in rendered, f"{protocol.__name__}.{method} exposes a Path"


def test_the_adapter_round_trips_a_dataset(tmp_path: Path) -> None:
    """Writing then reading returns the same frame."""
    adapter = ParquetAdapter(tmp_path)
    frame = pl.DataFrame({"thing_id": [1, 2, 3]})

    written = adapter.write({"things": frame})
    read_back = adapter.read(["things"])

    assert written == (
        WriteResult(dataset="things", location=str(tmp_path / "things.parquet"), rows=3),
    )
    assert read_back["things"].equals(frame)


def test_a_write_result_records_what_landed_where(tmp_path: Path) -> None:
    """Every adapter can answer what it wrote, where, and how much."""
    adapter = ParquetAdapter(tmp_path)

    results = adapter.write({"a": pl.DataFrame({"x": [1]}), "b": pl.DataFrame({"x": [1, 2]})})

    assert [result.dataset for result in results] == ["a", "b"]
    assert [result.rows for result in results] == [1, 2]
    assert all(result.location.endswith(".parquet") for result in results)


@pytest.mark.parametrize(
    ("dataset", "location", "rows"),
    [("", "somewhere", 1), ("things", "  ", 1), ("things", "somewhere", -1)],
)
def test_an_incoherent_write_result_is_rejected(dataset: str, location: str, rows: int) -> None:
    """A result that cannot be traced back to what was written is an error."""
    with pytest.raises(ValueError):
        WriteResult(dataset=dataset, location=location, rows=rows)


def test_a_missing_dataset_raises_an_adapter_error(tmp_path: Path) -> None:
    """Adapter failures surface as AdapterError, not a storage-specific type."""
    adapter = ParquetAdapter(tmp_path)

    with pytest.raises(AdapterError):
        adapter.read(["absent"])
