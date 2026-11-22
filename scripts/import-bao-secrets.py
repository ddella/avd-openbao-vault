#!/usr/bin/env python3
"""Import non-null secrets from a Bao environment YAML file.

Copy the template to the .secrets/ directory and add the secrets
  cp bao-secrets-template.yml .secrets/bao-secrets-net-prod.yml

Create policy and users for OpenBao:

Usage:
  python3 scripts/import-bao-secrets.py .secrets/bao-secrets-net-prod.yml --dry-run
  python3 scripts/import-bao-secrets.py .secrets/bao-secrets-net-prod.yml
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml


class TemplateError(ValueError):
    """Raised when the input file does not match the Bao template shape."""


class BaoCommandError(RuntimeError):
    """Raised when Bao rejects a secret write for a reason other than CAS conflict."""


def path_segment(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise TemplateError(f"{label} must contain only letters, digits, '_' or '-'")
    return value


def without_nulls(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        cleaned = {
            key: item
            for key, value in value.items()
            if (item := without_nulls(value)) is not None
            and not (isinstance(item, (dict, list)) and not item)
        }
        return cleaned or None
    if isinstance(value, list):
        cleaned = [
            item
            for value in value
            if (item := without_nulls(value)) is not None
            and not (isinstance(item, (dict, list)) and not item)
        ]
        return cleaned or None
    return value


def nonempty(value: Any) -> bool:
    return value is not None and value != {} and value != []


def merge_values(existing: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    for key, value in updates.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = merge_values(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_plan(template_path: Path) -> tuple[str, list[tuple[str, dict[str, Any]]]]:
    try:
        with template_path.open(encoding="utf-8") as template_file:
            data = yaml.safe_load(template_file)
    except OSError as error:
        raise TemplateError(f"cannot read {template_path}: {error}") from error
    except yaml.YAMLError as error:
        raise TemplateError(f"invalid YAML in {template_path}: {error}") from error

    if not isinstance(data, dict):
        raise TemplateError("the YAML root must be a mapping")
    extra_keys = set(data) - {"environment", "global", "datacenters"}
    if extra_keys:
        raise TemplateError(f"unexpected top-level keys: {', '.join(map(str, sorted(extra_keys)))}")

    environment = path_segment(data.get("environment"), "environment")
    global_secrets = data.get("global")
    datacenters = data.get("datacenters")
    if not isinstance(global_secrets, dict) or not isinstance(datacenters, dict):
        raise TemplateError("'global' and 'datacenters' must both be mappings")

    plan: list[tuple[str, dict[str, Any]]] = []
    for category, values in global_secrets.items():
        category = path_segment(category, "global category")
        if not isinstance(values, dict):
            raise TemplateError(f"global.{category} must be a mapping")
        cleaned = without_nulls(values)
        if nonempty(cleaned):
            plan.append((f"global/{category}", cleaned))

    for datacenter, categories in datacenters.items():
        datacenter = path_segment(datacenter, "datacenter")
        if not isinstance(categories, dict):
            raise TemplateError(f"datacenters.{datacenter} must be a mapping")
        for category, values in categories.items():
            category = path_segment(category, f"datacenters.{datacenter} category")
            if not isinstance(values, dict):
                raise TemplateError(f"datacenters.{datacenter}.{category} must be a mapping")
            cleaned = without_nulls(values)
            if nonempty(cleaned):
                plan.append((f"dc/{datacenter}/{category}", cleaned))

    return environment, plan


def bao_command(bao_cli: str, operation: list[str], mount: str, args: argparse.Namespace) -> list[str]:
    command = [bao_cli, *operation]
    if args.address:
        command.append(f"-address={args.address}")
    if args.namespace:
        command.append(f"-namespace={args.namespace}")
    if args.ca_cert:
        command.append(f"-ca-cert={args.ca_cert}")
    command.append(f"-mount={mount}")
    return command


def read_secret(
    bao_cli: str,
    mount: str,
    secret_path: str,
    args: argparse.Namespace,
) -> tuple[dict[str, Any] | None, int | None]:
    command = bao_command(bao_cli, ["kv", "get", "-format=json"], mount, args)
    command.append(secret_path)
    result = subprocess.run(command, capture_output=True, text=True)

    if result.returncode != 0:
        error_output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        if "no value found" in error_output.casefold() or "secret not found" in error_output.casefold():
            return None, None
        raise BaoCommandError(error_output.strip() or f"Bao exited with status {result.returncode}")

    try:
        response = json.loads(result.stdout)
        secret_data = response["data"]["data"]
        version = int(response["data"]["metadata"]["version"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise BaoCommandError(f"Unexpected JSON response reading {mount}/{secret_path}") from error

    if not isinstance(secret_data, dict):
        raise BaoCommandError(f"Secret data at {mount}/{secret_path} is not a JSON object")
    return secret_data, version


def write_secret(
    bao_cli: str,
    mount: str,
    secret_path: str,
    values: dict[str, Any],
    cas_version: int,
    args: argparse.Namespace,
) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix="bao-secret-", suffix=".json", delete=False
    ) as json_file:
        json.dump(values, json_file, ensure_ascii=False)
        json_path = Path(json_file.name)

    command = bao_command(bao_cli, ["kv", "put", f"-cas={cas_version}"], mount, args)
    command.extend([secret_path, f"@{json_path}"])

    try:
        result = subprocess.run(command, capture_output=True, text=True)
    finally:
        json_path.unlink(missing_ok=True)

    if result.returncode != 0:
        error_output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        raise BaoCommandError(error_output.strip() or f"Bao exited with status {result.returncode}")


def import_secret(
    bao_cli: str,
    mount: str,
    secret_path: str,
    updates: dict[str, Any],
    args: argparse.Namespace,
) -> None:
    target = f"{mount}/{secret_path}"
    existing, current_version = read_secret(bao_cli, mount, secret_path, args)

    if existing is None:
        merged = updates
        cas_version = 0
        action = "Created"
    elif args.overwrite:
        merged = updates
        cas_version = current_version
        action = "Replaced"
    else:
        merged = merge_values(existing, updates)
        cas_version = current_version
        action = "Updated"

    if existing is not None and merged == existing:
        print(f"Already up to date: {target}")
        return

    write_secret(bao_cli, mount, secret_path, merged, cas_version, args)
    print(f"{action}: {target}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write non-null values from a Bao environment YAML file to OpenBao KV v2."
    )
    parser.add_argument("input_file", type=Path, help="environment YAML file to import")
    parser.add_argument("--bao-cli", default="bao", help="Bao CLI executable (default: bao)")
    parser.add_argument("--address", help="OpenBao address; otherwise BAO_ADDR or CLI default is used")
    parser.add_argument("--namespace", help="OpenBao namespace, if applicable")
    parser.add_argument("--ca-cert", help="PEM CA certificate for the OpenBao server")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace the entire category payload instead of merging (omitted fields are removed)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print target paths without writing secret values"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        mount, plan = load_plan(args.input_file)
        if not plan:
            print(f"No non-null secrets found in {args.input_file}; nothing to write.")
            return 0

        for secret_path, values in plan:
            target = f"{mount}/{secret_path}"
            if args.dry_run:
                action = "replace" if args.overwrite else "merge or create"
                print(f"Would {action}: {target}")
                continue
            import_secret(args.bao_cli, mount, secret_path, values, args)
    except (TemplateError, BaoCommandError, FileNotFoundError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())