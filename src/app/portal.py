"""Employee sign-in and human review of locally stored HR/PTO requests."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[2]
USERS_FILE = ROOT / "data" / "portal_users.json"
TICKETS_FILE = ROOT / "data" / "tickets.jsonl"
REVIEWS_FILE = ROOT / "data" / "ticket_reviews.jsonl"
_review_lock = threading.Lock()


def password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 390_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, expected = stored.split("$", 2)
        return hmac.compare_digest(password_hash(password, salt), stored)
    except (ValueError, TypeError):
        return False


def employee(employee_id: str, employees_file: Path) -> dict[str, Any] | None:
    records = json.loads(employees_file.read_text(encoding="utf-8")).get("employees", [])
    return next((item for item in records if item.get("employee_id") == employee_id), None)


def authenticate(employee_id: str, password: str, employees_file: Path) -> bool:
    if not USERS_FILE.is_file() or not employee(employee_id, employees_file):
        return False
    users = json.loads(USERS_FILE.read_text(encoding="utf-8"))
    return verify_password(password, users.get(employee_id, ""))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def all_tickets(employees_file: Path) -> list[dict[str, Any]]:
    """Overlay append-only decisions on MCP tickets and seeded demo PTO requests."""
    employees = json.loads(employees_file.read_text(encoding="utf-8")).get("employees", [])
    names = {person["employee_id"]: person["name"] for person in employees}
    tickets = {item["ticket_id"]: item for item in _jsonl(TICKETS_FILE) if "ticket_id" in item}
    for person in employees:
        for request in person.get("pending_pto_requests", []):
            ticket_id = request.get("request_id")
            if ticket_id and ticket_id not in tickets:
                tickets[ticket_id] = {
                    "ticket_id": ticket_id, "employee_id": person["employee_id"],
                    "ticket_type": "pto_request", "subject": "PTO request",
                    "description": request.get("reason", ""),
                    "requested_start_date": request.get("start_date"),
                    "requested_end_date": request.get("end_date"),
                    "status": "created", "created_at": request.get("start_date", ""),
                }
    for decision in _jsonl(REVIEWS_FILE):
        ticket = tickets.get(decision.get("ticket_id"))
        if ticket:
            ticket.update({key: decision[key] for key in ("status", "review_message", "reviewer_id", "reviewed_at")})
    result = []
    for ticket in tickets.values():
        item = ticket.copy()
        item["employee_name"] = names.get(item.get("employee_id"), item.get("employee_id"))
        result.append(item)
    return sorted(result, key=lambda item: item.get("created_at", ""), reverse=True)


def can_review(reviewer: dict[str, Any], ticket: dict[str, Any], employees_file: Path) -> bool:
    if ticket.get("employee_id") == reviewer.get("employee_id"):
        return False
    if ticket.get("ticket_type") == "pto_request":
        # The employee's actual manager, not any manager or HR user.
        owner = employee(ticket["employee_id"], employees_file)
        return bool(owner and owner.get("manager_id") == reviewer["employee_id"])
    return reviewer.get("department") == "People Operations"


def review_ticket(ticket_id: str, reviewer: dict[str, Any], status: str, message: str, employees_file: Path) -> dict[str, Any]:
    if status not in ("approved", "denied") or not message.strip():
        raise ValueError("Select approve or deny and include a message.")
    with _review_lock:
        ticket = next((item for item in all_tickets(employees_file) if item["ticket_id"] == ticket_id), None)
        if not ticket:
            raise LookupError("Request not found")
        if not can_review(reviewer, ticket, employees_file):
            raise PermissionError("You are not the assigned reviewer for this request")
        if ticket.get("status") not in ("created", "pending"):
            raise ValueError("This request has already been reviewed")
        decision = {"ticket_id": ticket_id, "status": status, "review_message": message.strip(),
                    "reviewer_id": reviewer["employee_id"], "reviewed_at": datetime.now(timezone.utc).isoformat()}
        REVIEWS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with REVIEWS_FILE.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(decision, ensure_ascii=False) + "\n")
        return {**ticket, **decision}
