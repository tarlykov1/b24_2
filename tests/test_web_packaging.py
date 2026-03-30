from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_MODULE_CONFIG_PATH = Path("/tmp/b24_web_packaging_import.yml")
if not _MODULE_CONFIG_PATH.exists():
    _MODULE_CONFIG_PATH.write_text(
        """
runtime_mode: test
database_url: sqlite+pysqlite:////tmp/b24_web_packaging_import.db
source:
  base_url: https://source
  webhook: one
target:
  base_url: https://target
  webhook: two
default_scope:
  - crm
  - tasks
""",
        encoding="utf-8",
    )
os.environ.setdefault("MIGRATION_CONFIG_PATH", str(_MODULE_CONFIG_PATH))

from b24_migrator.web.app import create_app


def _write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "migration.config.yml"
    db_path = tmp_path / "runtime.db"
    config_path.write_text(
        f"""
runtime_mode: test
database_url: sqlite+pysqlite:///{db_path}
source:
  base_url: https://source
  webhook: one
target:
  base_url: https://target
  webhook: two
default_scope:
  - crm
  - tasks
""",
        encoding="utf-8",
    )
    return config_path


def test_create_app_skips_static_mount_if_directory_missing(tmp_path: Path, monkeypatch) -> None:
    original_is_dir = Path.is_dir

    def fake_is_dir(path_obj: Path) -> bool:
        if path_obj.name == "static":
            return False
        return original_is_dir(path_obj)

    monkeypatch.setattr(Path, "is_dir", fake_is_dir)

    app = create_app(str(_write_config(tmp_path)))

    assert app.state.static_enabled is False
    assert all(route.path != "/static" for route in app.routes)


def test_installed_package_contains_web_assets(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    install_target = tmp_path / "site"
    install_target.mkdir()

    install_cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        ".",
        "--no-deps",
        "--ignore-requires-python",
        "--no-build-isolation",
        "--target",
        str(install_target),
    ]
    install_proc = subprocess.run(install_cmd, cwd=repo_root, check=False, capture_output=True, text=True)
    assert install_proc.returncode == 0, install_proc.stderr

    check_code = (
        "from importlib.util import find_spec\n"
        "from pathlib import Path\n"
        "spec=find_spec('b24_migrator.web')\n"
        "assert spec and spec.origin\n"
        "pkg=Path(spec.origin).parent\n"
        "assert (pkg/'static').is_dir(), pkg/'static'\n"
        "assert (pkg/'templates').is_dir(), pkg/'templates'\n"
        "print('ok')\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(install_target)
    check_proc = subprocess.run([sys.executable, "-c", check_code], env=env, check=False, capture_output=True, text=True)
    assert check_proc.returncode == 0, check_proc.stderr
