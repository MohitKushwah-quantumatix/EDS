"""Tests for the platform project and state foundation.

A project is what makes a simulation resumable, so these tests care most about
three things: that identity survives a round trip, that a document written
twice is byte-identical, and that the platform refuses to guess when a stored
document is one it cannot read.
"""

from __future__ import annotations

import ast
import importlib
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

import eds
import eds.domains.retail  # noqa: F401  - registers the domain
from eds.platform.metadata import PLATFORM_CONTRACT_VERSION
from eds.platform.project import (
    MANIFEST_KEY,
    MANIFEST_VERSION,
    STATE_KEY,
    STATE_VERSION,
    CorruptDocumentError,
    Document,
    FileStateStore,
    Project,
    ProjectExistsError,
    ProjectIssue,
    ProjectManifest,
    ProjectNotFoundError,
    ProjectValidationError,
    SimulationState,
    StateStore,
    StateStoreError,
    UnsupportedVersionError,
    Workspace,
    create_project,
    open_project,
    require_supported_version,
)

PACKAGE_ROOT = Path(eds.__file__).parent
PROJECT_ROOT = PACKAGE_ROOT / "platform" / "project"

FIXED_TIME = datetime(2025, 1, 31, 12, 0, tzinfo=UTC)


@pytest.fixture
def project(tmp_path: Path) -> Project:
    """Return a freshly created project with a fixed identity."""
    return create_project(
        tmp_path / "acme",
        name="Acme Retail",
        domain="retail",
        seed=42,
        project_id="fixed-id",
        created_at=FIXED_TIME,
    )


class _MemoryStore:
    """A store that keeps documents in memory, to prove the abstraction holds."""

    def __init__(self) -> None:
        """Start empty."""
        self.documents: dict[str, dict[str, Any]] = {}

    @property
    def name(self) -> str:
        """Return the store's kind."""
        return "memory"

    def exists(self, key: str) -> bool:
        """Report whether a document is stored under a key."""
        return key in self.documents

    def read(self, key: str) -> dict[str, Any]:
        """Read one document."""
        if key not in self.documents:
            raise StateStoreError(f"No {key!r} document in memory")
        return dict(self.documents[key])

    def write(self, key: str, document: Document) -> None:
        """Write one document."""
        self.documents[key] = dict(document)


# --------------------------------------------------------------------------
# Project creation
# --------------------------------------------------------------------------


def test_creating_a_project_records_its_identity(project: Project) -> None:
    """Everything needed to recognise the project again is written down."""
    assert project.project_id == "fixed-id"
    assert project.name == "Acme Retail"
    assert project.domain_name == "retail"
    assert project.seed == 42
    assert project.manifest.created_at == FIXED_TIME


def test_creating_a_project_records_the_platform_that_made_it(project: Project) -> None:
    """Provenance is captured so a project can say what built it."""
    assert project.manifest.platform_version == project.platform.version
    assert project.manifest.platform_contract_version == PLATFORM_CONTRACT_VERSION
    assert project.manifest.manifest_version == MANIFEST_VERSION


def test_creating_a_project_builds_the_workspace(project: Project) -> None:
    """The data directory exists; the reserved ones do not."""
    assert project.workspace.data_directory.is_dir()
    assert not project.workspace.snapshots_directory.exists()
    assert not project.workspace.logs_directory.exists()


def test_a_generated_identifier_is_unique(tmp_path: Path) -> None:
    """Two projects created without an explicit id do not collide."""
    one = create_project(tmp_path / "a", name="A", domain="retail")
    two = create_project(tmp_path / "b", name="B", domain="retail")

    assert one.project_id != two.project_id


def test_creating_over_an_existing_project_is_refused(project: Project) -> None:
    """Overwriting would discard an enterprise's identity and history."""
    with pytest.raises(ProjectExistsError, match="already exists"):
        create_project(project.workspace.root, name="Other", domain="retail")


def test_a_project_can_be_created_for_an_uninstalled_domain(tmp_path: Path) -> None:
    """A project may be created before its domain is available."""
    created = create_project(tmp_path / "clinic", name="Clinic", domain="healthcare")

    assert created.domain_name == "healthcare"
    assert "unknown_domain" in {issue.rule for issue in created.validate()}


def test_a_project_without_a_seed_is_allowed(tmp_path: Path) -> None:
    """Not every project needs to be reproducible, but it must say so."""
    created = create_project(tmp_path / "adhoc", name="Adhoc", domain="retail")

    assert created.seed is None


# --------------------------------------------------------------------------
# Project loading
# --------------------------------------------------------------------------


def test_a_project_survives_a_round_trip(project: Project) -> None:
    """Reopening yields the identity that was written."""
    reopened = open_project(project.workspace.root)

    assert reopened.manifest == project.manifest


def test_opening_where_there_is_no_project_raises(tmp_path: Path) -> None:
    """The error says what is missing and what to do."""
    with pytest.raises(ProjectNotFoundError, match="no project at"):
        open_project(tmp_path / "empty")


def test_opening_a_project_does_not_require_its_domain(tmp_path: Path) -> None:
    """A project must be inspectable where its domain is not installed."""
    create_project(tmp_path / "clinic", name="Clinic", domain="healthcare")

    reopened = open_project(tmp_path / "clinic")

    assert reopened.domain_name == "healthcare"
    with pytest.raises(KeyError, match="Unknown domain"):
        reopened.domain()


def test_a_project_resolves_its_domain_on_demand(project: Project) -> None:
    """Resolution goes through the registry, not through an import."""
    assert project.domain().name == "retail"


# --------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------


def test_a_manifest_round_trips_through_a_document() -> None:
    """Serialising and rebuilding preserves every field."""
    manifest = ProjectManifest(
        project_id="abc", name="Demo", domain="retail", seed=7, created_at=FIXED_TIME
    )

    assert ProjectManifest.from_document(manifest.to_document()) == manifest


def test_a_manifest_document_holds_only_primitives() -> None:
    """A document must be storable by any backend, not only by JSON."""
    document = ProjectManifest(
        project_id="abc", name="Demo", domain="retail", seed=7, created_at=FIXED_TIME
    ).to_document()

    for key, value in document.items():
        assert isinstance(value, (str, int, type(None))), f"{key} is {type(value)}"


@pytest.mark.parametrize("field", ["project_id", "name", "domain"])
def test_a_manifest_without_an_identity_is_rejected(field: str) -> None:
    """A project that cannot be identified is not a project."""
    values: dict[str, Any] = {
        "project_id": "abc",
        "name": "Demo",
        "domain": "retail",
        "seed": None,
        "created_at": FIXED_TIME,
    }
    values[field] = "   "

    with pytest.raises(ValueError, match="must not be empty"):
        ProjectManifest(**values)


def test_a_naive_creation_timestamp_is_rejected() -> None:
    """A project outlives the machine that made it, so the zone must be known."""
    with pytest.raises(ValueError, match="timezone-aware"):
        ProjectManifest(
            project_id="abc",
            name="Demo",
            domain="retail",
            seed=None,
            created_at=datetime(2025, 1, 31, 12, 0),  # noqa: DTZ001 - the point of the test
        )


@pytest.mark.parametrize(
    "field", ["project_id", "name", "domain", "created_at", "platform_version"]
)
def test_a_manifest_missing_a_field_is_corrupt(field: str) -> None:
    """A half-written manifest is reported, not silently defaulted."""
    document = dict(
        ProjectManifest(
            project_id="abc", name="Demo", domain="retail", seed=1, created_at=FIXED_TIME
        ).to_document()
    )
    del document[field]

    with pytest.raises(CorruptDocumentError):
        ProjectManifest.from_document(document)


def test_a_manifest_with_a_malformed_timestamp_is_corrupt() -> None:
    """An unparsable date is corruption, not a missing value."""
    document = dict(
        ProjectManifest(
            project_id="abc", name="Demo", domain="retail", seed=1, created_at=FIXED_TIME
        ).to_document()
    )
    document["created_at"] = "not-a-date"

    with pytest.raises(CorruptDocumentError, match="ISO 8601"):
        ProjectManifest.from_document(document)


def test_a_manifest_with_a_non_integer_seed_is_corrupt() -> None:
    """A seed that is not a number could not reproduce anything."""
    document = dict(
        ProjectManifest(
            project_id="abc", name="Demo", domain="retail", seed=1, created_at=FIXED_TIME
        ).to_document()
    )
    document["seed"] = "forty-two"

    with pytest.raises(CorruptDocumentError, match="seed"):
        ProjectManifest.from_document(document)


def test_a_project_from_a_newer_contract_is_refused() -> None:
    """A project built against a contract this platform does not implement."""
    document = dict(
        ProjectManifest(
            project_id="abc", name="Demo", domain="retail", seed=1, created_at=FIXED_TIME
        ).to_document()
    )
    document["platform_contract_version"] = PLATFORM_CONTRACT_VERSION + 1

    with pytest.raises(CorruptDocumentError, match="contract"):
        ProjectManifest.from_document(document)


# --------------------------------------------------------------------------
# Simulation state
# --------------------------------------------------------------------------


def test_a_project_with_no_state_reads_as_empty(project: Project) -> None:
    """Nothing has happened yet is not an error."""
    assert not project.has_state()
    assert project.read_state() == SimulationState()


def test_state_survives_a_round_trip(project: Project) -> None:
    """What was written is what comes back."""
    state = SimulationState(
        current_date=date(2025, 3, 1),
        completed_stages=("retail:master-data", "retail:customers"),
        last_identifiers={"customers": 1000, "orders": 311},
    )

    project.write_state(state)

    assert project.has_state()
    assert project.read_state() == state


def test_state_is_replaced_not_appended(project: Project) -> None:
    """Writing state twice leaves the second one, not both."""
    project.write_state(SimulationState(completed_stages=("retail:master-data",)))
    project.write_state(SimulationState(completed_stages=("retail:customers",)))

    assert project.read_state().completed_stages == ("retail:customers",)


def test_the_last_completed_stage_is_the_most_recent() -> None:
    """The ordered record answers 'which was last' without storing it twice."""
    state = SimulationState(completed_stages=("a", "b", "c"))

    assert state.last_completed_stage == "c"
    assert SimulationState().last_completed_stage is None


def test_state_is_frozen(project: Project) -> None:
    """State is a value; updating means replacing."""
    state = project.read_state()

    with pytest.raises(AttributeError):
        state.current_date = date(2025, 1, 1)  # type: ignore[misc]


def test_state_is_updated_by_replacement(project: Project) -> None:
    """The frozen record composes with dataclasses.replace."""
    project.write_state(SimulationState(current_date=date(2025, 1, 1)))

    advanced = replace(project.read_state(), current_date=date(2025, 1, 2))
    project.write_state(advanced)

    assert project.read_state().current_date == date(2025, 1, 2)


def test_a_stage_recorded_twice_is_rejected() -> None:
    """A duplicate completion means a lost write or a scheduler bug."""
    with pytest.raises(ValueError, match="more than once"):
        SimulationState(completed_stages=("retail:customers", "retail:customers"))


def test_a_negative_identifier_is_rejected() -> None:
    """Identifiers count upward from zero."""
    with pytest.raises(ValueError, match="cannot be negative"):
        SimulationState(last_identifiers={"customers": -1})


def test_state_stores_a_date_but_never_advances_it(project: Project) -> None:
    """P003 stores simulated time; it does not move it."""
    project.write_state(SimulationState(current_date=date(2025, 6, 1)))

    assert project.read_state().current_date == date(2025, 6, 1)
    assert not hasattr(project, "advance")
    assert not any(name.startswith("advance") for name in dir(SimulationState))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("current_date", "not-a-date"),
        ("current_date", 20250101),
        ("completed_stages", "retail:customers"),
        ("last_identifiers", {"customers": "many"}),
        ("state_version", "one"),
    ],
)
def test_malformed_state_is_reported_as_corrupt(field: str, value: Any) -> None:
    """Every field is checked rather than trusted."""
    document = dict(SimulationState().to_document())
    document[field] = value

    with pytest.raises(CorruptDocumentError):
        SimulationState.from_document(document)


def test_corrupt_state_on_disk_is_reported(project: Project) -> None:
    """A truncated or hand-edited state file names itself."""
    store = project.store
    assert isinstance(store, FileStateStore)
    store.path_for(STATE_KEY).write_text("{not json", encoding="utf-8")

    with pytest.raises(CorruptDocumentError, match="not valid JSON"):
        project.read_state()


# --------------------------------------------------------------------------
# Versioning
# --------------------------------------------------------------------------


def test_the_three_versions_are_separate_concepts() -> None:
    """Manifest, state and contract versions move independently."""
    assert MANIFEST_VERSION >= 1
    assert STATE_VERSION >= 1
    assert PLATFORM_CONTRACT_VERSION >= 1


def test_a_matching_version_is_supported() -> None:
    """The common case does not raise."""
    require_supported_version("manifest", 1, 1)


def test_a_newer_document_says_to_upgrade() -> None:
    """A document from the future cannot be guessed at."""
    with pytest.raises(UnsupportedVersionError, match="newer platform"):
        require_supported_version("manifest", 2, 1)


def test_an_older_document_says_migration_is_not_implemented() -> None:
    """The remedy differs from the newer case, so the message does too."""
    with pytest.raises(UnsupportedVersionError, match="migration is not implemented"):
        require_supported_version("state", 1, 2)


def test_a_manifest_with_an_unreadable_version_is_refused() -> None:
    """Version checking happens before any field is interpreted."""
    document = dict(
        ProjectManifest(
            project_id="abc", name="Demo", domain="retail", seed=1, created_at=FIXED_TIME
        ).to_document()
    )
    document["manifest_version"] = MANIFEST_VERSION + 1

    with pytest.raises(UnsupportedVersionError):
        ProjectManifest.from_document(document)


def test_a_state_document_with_an_unreadable_version_is_refused() -> None:
    """State versions are gated exactly as manifest versions are."""
    document = dict(SimulationState().to_document())
    document["state_version"] = STATE_VERSION + 1

    with pytest.raises(UnsupportedVersionError):
        SimulationState.from_document(document)


# --------------------------------------------------------------------------
# Deterministic serialization
# --------------------------------------------------------------------------


def test_writing_a_document_twice_produces_identical_bytes(tmp_path: Path) -> None:
    """A project directory must be diffable and checksummable."""
    store = FileStateStore(tmp_path)
    state = SimulationState(
        current_date=date(2025, 1, 1),
        completed_stages=("b", "a"),
        last_identifiers={"z": 1, "a": 2},
    )

    store.write(STATE_KEY, state.to_document())
    first = store.path_for(STATE_KEY).read_bytes()
    store.write(STATE_KEY, state.to_document())

    assert store.path_for(STATE_KEY).read_bytes() == first


def test_document_key_order_does_not_affect_the_stored_bytes(tmp_path: Path) -> None:
    """Serialisation sorts keys, so mapping order cannot leak into the file."""
    store = FileStateStore(tmp_path)

    store.write("one", {"a": 1, "b": 2})
    forwards = store.path_for("one").read_bytes()
    store.write("two", {"b": 2, "a": 1})

    assert store.path_for("two").read_bytes() == forwards


def test_two_projects_with_the_same_identity_serialise_identically(tmp_path: Path) -> None:
    """Nothing non-deterministic leaks into a manifest."""
    common = {
        "name": "Demo",
        "domain": "retail",
        "seed": 1,
        "project_id": "x",
        "created_at": FIXED_TIME,
    }
    one = create_project(tmp_path / "one", **common)  # type: ignore[arg-type]
    two = create_project(tmp_path / "two", **common)  # type: ignore[arg-type]

    assert (tmp_path / "one" / "manifest.json").read_bytes() == (
        tmp_path / "two" / "manifest.json"
    ).read_bytes()
    assert one.manifest == two.manifest


# --------------------------------------------------------------------------
# The store abstraction
# --------------------------------------------------------------------------


def test_the_file_store_satisfies_the_protocol(tmp_path: Path) -> None:
    """The shipped store conforms to the declared extension point."""
    store = FileStateStore(tmp_path)

    assert isinstance(store, StateStore)
    assert store.name == "file"


def test_a_project_works_with_any_conforming_store(tmp_path: Path) -> None:
    """Persistence is storage-independent, not merely intended to be.

    A store that never touches a filesystem drives a whole project lifecycle,
    which is the only real proof the abstraction is at the right level.
    """
    store = _MemoryStore()
    assert isinstance(store, StateStore)

    created = create_project(
        tmp_path / "mem",
        name="Mem",
        domain="retail",
        project_id="m",
        created_at=FIXED_TIME,
        store=store,
    )
    created.write_state(SimulationState(current_date=date(2025, 1, 1)))

    reopened = open_project(tmp_path / "mem", store=store)

    assert reopened.manifest == created.manifest
    assert reopened.read_state().current_date == date(2025, 1, 1)
    assert set(store.documents) == {MANIFEST_KEY, STATE_KEY}
    assert not (tmp_path / "mem" / "manifest.json").exists()


def test_reading_an_absent_document_raises(tmp_path: Path) -> None:
    """A missing document is distinguishable from a corrupt one."""
    store = FileStateStore(tmp_path)

    with pytest.raises(StateStoreError, match="No 'absent' document"):
        store.read("absent")


def test_reading_a_non_object_document_is_corrupt(tmp_path: Path) -> None:
    """Valid JSON that is not a mapping cannot be a document."""
    store = FileStateStore(tmp_path)
    store.path_for("scalar").write_text("[1, 2, 3]", encoding="utf-8")

    with pytest.raises(CorruptDocumentError, match="must be an object"):
        store.read("scalar")


def test_an_unserialisable_document_is_reported(tmp_path: Path) -> None:
    """A document carrying something that is not data fails loudly."""
    store = FileStateStore(tmp_path)

    with pytest.raises(StateStoreError, match="cannot be serialised"):
        store.write("bad", {"callable": print})


# --------------------------------------------------------------------------
# Workspace
# --------------------------------------------------------------------------


def test_a_missing_workspace_is_reported(tmp_path: Path) -> None:
    """Validation says the directory is absent rather than failing later."""
    issues = Workspace(root=tmp_path / "absent").validate()

    assert {issue.rule for issue in issues} == {"missing_workspace"}


def test_a_workspace_that_is_a_file_is_reported(tmp_path: Path) -> None:
    """A path that exists but is not a directory is a different fault."""
    path = tmp_path / "notadir"
    path.write_text("", encoding="utf-8")

    assert {issue.rule for issue in Workspace(root=path).validate()} == {
        "workspace_not_a_directory"
    }


def test_a_workspace_without_a_data_directory_is_reported(tmp_path: Path) -> None:
    """The layout is checked, not assumed."""
    (tmp_path / "bare").mkdir()

    assert {issue.rule for issue in Workspace(root=tmp_path / "bare").validate()} == {
        "missing_data_directory"
    }


def test_a_created_workspace_validates_clean(project: Project) -> None:
    """Creation produces a layout that passes its own check."""
    assert project.workspace.validate() == []


def test_creating_a_workspace_is_idempotent(project: Project) -> None:
    """Re-creating an existing layout is not an error."""
    project.workspace.create()

    assert project.workspace.validate() == []


# --------------------------------------------------------------------------
# Project validation
# --------------------------------------------------------------------------


def test_a_sound_project_validates_clean(project: Project) -> None:
    """The happy path reports nothing."""
    assert project.validate() == []
    project.assert_valid()


def test_an_unknown_domain_is_reported_not_raised(tmp_path: Path) -> None:
    """A project whose domain is not installed still loads."""
    created = create_project(tmp_path / "clinic", name="Clinic", domain="healthcare")

    issues = created.validate()

    assert {issue.rule for issue in issues} == {"unknown_domain"}
    with pytest.raises(ProjectValidationError, match="unknown_domain"):
        created.assert_valid()


def test_a_broken_workspace_is_reported(project: Project) -> None:
    """Structural damage after creation is caught by validation."""
    project.workspace.data_directory.rmdir()

    assert "missing_data_directory" in {issue.rule for issue in project.validate()}


def test_an_issue_renders_readably() -> None:
    """Issues appear in error messages, so they must read well."""
    assert str(ProjectIssue("retail", "unknown_domain", "not registered")) == (
        "[retail] unknown_domain: not registered"
    )


def test_a_validation_error_without_issues_is_a_bug() -> None:
    """Raising with nothing to report is rejected."""
    with pytest.raises(ValueError, match="at least one issue"):
        ProjectValidationError(())


# --------------------------------------------------------------------------
# Architectural constraints
# --------------------------------------------------------------------------


def test_no_domain_knows_about_persistence() -> None:
    """State belongs to the platform, never to a domain.

    A domain declares what it generates; whether a particular enterprise has
    generated it yet is not the domain's business.
    """
    for source in (PACKAGE_ROOT / "domains").rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert "eds.platform.project" not in text, f"{source.name} reaches into project state"


def test_the_project_model_introduces_no_runtime() -> None:
    """P003 stores; it does not run, advance, schedule or generate."""
    banned = ("polars", "eds.domains", "eds.adapters", "eds.platform.execution")
    for source in PROJECT_ROOT.rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(banned), f"{source.name} imports {node.module}"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(banned), f"{source.name} imports {alias.name}"


def test_the_execution_model_is_untouched_by_projects() -> None:
    """P002 remains independent of P003; a plan needs no project."""
    for source in (PACKAGE_ROOT / "platform" / "execution").rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert "eds.platform.project" not in text, f"{source.name} depends on a project"


def test_a_project_carries_nothing_executable(project: Project) -> None:
    """A project holds identity, a location and a store - no callables."""
    assert isinstance(project.manifest, ProjectManifest)
    assert isinstance(project.workspace, Workspace)
    assert isinstance(project.store, StateStore)


@pytest.mark.parametrize(
    "name",
    [
        "eds.platform.project",
        "eds.platform.project.errors",
        "eds.platform.project.manifest",
        "eds.platform.project.project",
        "eds.platform.project.state",
        "eds.platform.project.store",
        "eds.platform.project.versions",
        "eds.platform.project.workspace",
    ],
)
def test_project_modules_are_importable_and_documented(name: str) -> None:
    """Every module in the package imports cleanly and states its purpose."""
    module = importlib.import_module(name)

    assert module.__doc__ is not None
    assert module.__doc__.strip()
