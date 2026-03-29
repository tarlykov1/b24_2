from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path


def test_install_generates_env_and_config_without_sigpipe(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    install_script = repo_root / "install.sh"

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker_log = tmp_path / "docker.log"
    fake_docker = bin_dir / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${FAKE_DOCKER_LOG}"
if [[ "$1" == "compose" && "$2" == "version" ]]; then
  exit 0
fi
if [[ "$1" == "compose" && "$2" == "up" ]]; then
  exit 0
fi
if [[ "$1" == "compose" && "$2" == "ps" && "$3" == "-q" ]]; then
  if [[ "$4" == "db" ]]; then
    printf 'db-container\n'
    exit 0
  fi
  if [[ "$4" == "web" ]]; then
    printf 'web-container\n'
    exit 0
  fi
fi
if [[ "$1" == "compose" && "$2" == "logs" ]]; then
  exit 0
fi
if [[ "$1" == "inspect" ]]; then
  printf 'healthy\n'
  exit 0
fi
exit 0
"""
    )
    fake_docker.chmod(fake_docker.stat().st_mode | stat.S_IXUSR)

    env_path = tmp_path / ".env"
    config_path = tmp_path / "migration.config.yml"

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["FAKE_DOCKER_LOG"] = str(docker_log)
    env["B24_ENV_PATH"] = str(env_path)
    env["B24_CONFIG_PATH"] = str(config_path)
    env["B24_INSTALL_STATE_DIR"] = str(tmp_path / "state")
    env["B24_WEB_PORT"] = "8080"

    result = subprocess.run(
        ["bash", str(install_script)],
        cwd=repo_root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert env_path.exists(), ".env was not generated"
    assert config_path.exists(), "migration.config.yml was not generated"

    env_data = env_path.read_text()
    mysql_password_match = re.search(r"^MYSQL_PASSWORD=([A-Za-z0-9]{32})$", env_data, re.MULTILINE)
    mysql_root_password_match = re.search(r"^MYSQL_ROOT_PASSWORD=([A-Za-z0-9]{32})$", env_data, re.MULTILINE)
    assert mysql_password_match, "MYSQL_PASSWORD was not generated as 32-char alnum"
    assert mysql_root_password_match, "MYSQL_ROOT_PASSWORD was not generated as 32-char alnum"

    config_data = config_path.read_text()
    assert "database_url: mysql+pymysql://" in config_data
    assert mysql_password_match.group(1) in config_data

    docker_calls = docker_log.read_text()
    assert "compose up -d --build" in docker_calls
    assert "compose ps -q db" in docker_calls
    assert "compose ps -q web" in docker_calls
