from pathlib import Path


README_PATH = Path("README.md")


def test_readme_mentions_runtime_mode_and_mysql_only_policy() -> None:
    content = README_PATH.read_text(encoding="utf-8")

    assert "runtime_mode" in content
    assert "MySQL-only" in content


def test_readme_cli_examples_match_current_commands() -> None:
    content = README_PATH.read_text(encoding="utf-8")

    for cmd in [
        "b24-runtime create-job",
        "b24-runtime status",
        "b24-runtime checkpoint",
        "b24-runtime execute",
        "b24-runtime report",
        "b24-runtime deployment:check",
        "b24-runtime plan",
        "b24-runtime verify",
    ]:
        assert cmd in content
