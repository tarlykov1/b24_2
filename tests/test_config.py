from pathlib import Path

import pytest

from b24_migrator.config import load_runtime_config
from b24_migrator.errors import AppError


def test_load_config_success(tmp_path: Path) -> None:
    cfg = tmp_path / "migration.config.yml"
    cfg.write_text(
        """
        database_url: mysql+pymysql://user:pass@localhost:3306/db
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

    assert result.database_url.startswith("mysql+")
    assert result.source.base_url == "https://source"


def test_load_config_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(AppError) as exc:
        load_runtime_config(tmp_path / "missing.yml")

    assert exc.value.code == "CONFIG_NOT_FOUND"
