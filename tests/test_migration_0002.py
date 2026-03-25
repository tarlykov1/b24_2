import importlib.util
from pathlib import Path


def _load_migration_module():
    migration_path = Path("alembic/versions/0002_runtime_state_domain_split.py")
    spec = importlib.util.spec_from_file_location("migration_0002", migration_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_legacy_job_id_is_deterministic_and_fits_column() -> None:
    module = _load_migration_module()

    plan_id = "a" * 64
    first = module._legacy_job_id(plan_id)
    second = module._legacy_job_id(plan_id)

    assert first == second
    assert len(first) <= 64
    assert first.startswith("legacy-aaaaaaaaaaaaaaaa-")
