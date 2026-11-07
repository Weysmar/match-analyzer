"""`ma-db upgrade`, `ma-db downgrade <revision>`, `ma-db current`. Uses DATABASE_URL."""

import argparse
import os
import sys

from ma_db import migrate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ma-db", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("upgrade", help="apply the migrations and set the roles' passwords")
    downgrade = commands.add_parser("downgrade", help="go back to a revision (`base`: everything)")
    downgrade.add_argument("revision")
    commands.add_parser("current", help="print the current and the latest revision")
    arguments = parser.parse_args(argv)

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    match arguments.command:
        case "upgrade":
            migrate.upgrade(url)
            passwords = {
                "ma_api": os.environ.get("API_DB_PASSWORD"),
                "ma_worker": os.environ.get("WORKER_DB_PASSWORD"),
            }
            for role, password in passwords.items():
                if password:
                    migrate.set_role_password(url, role, password)
        case "downgrade":
            migrate.downgrade(url, arguments.revision)
        case "current":
            print(f"current: {migrate.current(url)}, latest: {migrate.head()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
