import importlib
from pathlib import Path

import pytest

from b24_migrator.config import load_runtime_config
from b24_migrator.errors import AppError


def test_load_config_success(tmp_path: Path) -> None:
    cfg = tmp_path / "migration.config.yml"
    cfg.write_text(
        """
        database_url: sqlite+pysqlite:///runtime.db
        source:
          base_url: https://source
          webhook: one
        target:
          base_url: https://target
          webhook: two
        """,
        encoding="utf-8",
    )

    result = load_runtime_config(cfg)

    assert result.database_url.startswith("sqlite+")
    assert result.source.base_url == "https://source"


def test_load_config_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(AppError) as exc:
        load_runtime_config(tmp_path / "missing.yml")

    assert exc.value.code == "CONFIG_NOT_FOUND"


def test_load_config_yaml_missing_dependency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "migration.config.yml"
    cfg.write_text("database_url: sqlite+pysqlite:///runtime.db", encoding="utf-8")

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None if name == "yaml" else object())

    with pytest.raises(AppError) as exc:
        load_runtime_config(cfg)

    assert exc.value.code == "CONFIG_DEPENDENCY_MISSING"


def test_load_config_yaml_parse_error(tmp_path: Path) -> None:
    cfg = tmp_path / "migration.config.yml"
    cfg.write_text("database_url: [", encoding="utf-8")

    with pytest.raises(AppError) as exc:
        load_runtime_config(cfg)

    assert exc.value.code == "CONFIG_YAML_PARSE_ERROR"
