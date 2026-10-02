"""One-time demo employee account provisioning (never commits the password)."""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path

from src.app.portal import USERS_FILE, password_hash


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--password-env", default="PORTAL_INITIAL_PASSWORD")
    args = parser.parse_args()
    password = os.getenv(args.password_env) or getpass.getpass("Initial employee password: ")
    if len(password) < 7:
        raise SystemExit("Password must have at least 7 characters")
    employees_file = Path(__file__).parents[1] / "data" / "employees.json"
    employees = json.loads(employees_file.read_text(encoding="utf-8"))["employees"]
    if USERS_FILE.exists():
        raise SystemExit(f"Refusing to overwrite existing account file: {USERS_FILE}")
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with USERS_FILE.open("x", encoding="utf-8") as stream:
        os.chmod(USERS_FILE, 0o600)
        json.dump({person["employee_id"]: password_hash(password) for person in employees}, stream)
    print(f"Provisioned {len(employees)} accounts in {USERS_FILE}")


if __name__ == "__main__":
    main()
