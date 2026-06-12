"""Create the initial admin user.

Examples:
    python scripts/create_admin.py --email admin@example.com --username admin
    python -m scripts.create_admin --username admin --password "..."

The users table currently stores username, not email. The email argument is
accepted for deployment ergonomics and used as username when --username is not
provided.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.security import hash_password  # noqa: E402
from core.entities.user import Role, User  # noqa: E402
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.repositories import SqlAlchemyUserRepository  # noqa: E402


async def _run(username: str, password: str, role: Role) -> int:
    session_factory = get_session_factory()
    async with session_factory() as session:
        repo = SqlAlchemyUserRepository(session)
        existing = await repo.find_by_username(username)
        if existing is not None:
            print(f"User already exists: username={username} id={existing.id} role={existing.role}")
            return 0

        user = User(
            id=None,
            username=username,
            password_hash=hash_password(password),
            role=role,
            is_active=True,
        )
        saved = await repo.save(user)
        await session.commit()
        print(f"Admin user created: id={saved.id} username={saved.username} role={saved.role}")
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create an initial AVM user.")
    parser.add_argument("--email", default=os.getenv("ADMIN_EMAIL"), help="Admin email (optional).")
    parser.add_argument("--username", default=os.getenv("ADMIN_USERNAME"), help="Unique username.")
    parser.add_argument("--password", default=os.getenv("ADMIN_PASSWORD"), help="Plain password.")
    parser.add_argument("--role", default=os.getenv("ADMIN_ROLE", "admin"), type=_validate_role)
    args = parser.parse_args(argv)

    username = args.username or args.email
    if not username:
        print("Missing --username or --email.", file=sys.stderr)
        return 1

    password = args.password or getpass.getpass(f"Password for {username}: ")
    if len(password) < 8:
        print("Password must have at least 8 characters.", file=sys.stderr)
        return 1

    return asyncio.run(_run(username=username, password=password, role=args.role))


def _validate_role(raw: str) -> Role:
    if raw in ("admin", "analyst", "viewer"):
        return raw  # type: ignore[return-value]
    raise argparse.ArgumentTypeError("role must be admin, analyst or viewer")


if __name__ == "__main__":
    raise SystemExit(main())
