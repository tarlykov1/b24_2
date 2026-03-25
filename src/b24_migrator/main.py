from __future__ import annotations

import json

import click

from b24_migrator.cli.app import app
from b24_migrator.cli.exit_codes import ExitCode


def run() -> None:
    """Entrypoint for console script."""

    try:
        app(standalone_mode=False)
    except click.UsageError as exc:
        payload = {
            "ok": False,
            "error_code": "UNKNOWN_COMMAND",
            "message": str(exc),
            "details": {"hint": "Run with --help for available commands"},
        }
        click.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        raise SystemExit(int(ExitCode.UNKNOWN_COMMAND)) from exc
    except click.ClickException as exc:
        payload = {
            "ok": False,
            "error_code": "RUNTIME_FAILURE",
            "message": str(exc),
            "details": {},
        }
        click.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        raise SystemExit(int(ExitCode.RUNTIME_FAILURE)) from exc
