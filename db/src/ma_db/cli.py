"""`ma-db upgrade`, `ma-db downgrade <revision>`, `ma-db current`; and the backups: `ma-db backup
[--every SECONDS]`, `ma-db backups`, `ma-db restore <key|latest> --into <URL>`. Uses DATABASE_URL,
the owner's connection; the backups also read `BACKUP_*` (ma_db.backup)."""

import argparse
import logging
import os
import sys
from datetime import UTC, datetime

from ma_db import backup, migrate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ma-db", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("upgrade", help="apply the migrations and set the roles' passwords")
    downgrade = commands.add_parser("downgrade", help="go back to a revision (`base`: everything)")
    downgrade.add_argument("revision")
    commands.add_parser("current", help="print the current and the latest revision")
    make = commands.add_parser("backup", help="back the database up to the backups bucket")
    make.add_argument(
        "--every", type=float, metavar="SECONDS", help="keep running: one backup every SECONDS"
    )
    commands.add_parser("backups", help="list the backups, oldest first")
    restore = commands.add_parser("restore", help="restore a backup into an EMPTY database")
    restore.add_argument("name", help="a key from `ma-db backups`, or `latest`")
    restore.add_argument(
        "--into", required=True, metavar="URL", help="the empty database to restore into"
    )
    arguments = parser.parse_args(argv)

    if arguments.command in ("backups", "restore"):
        try:
            store = backup.S3Store(backup.settings_from(os.environ))
            if arguments.command == "backups":
                print("\n".join(backup.backups(store)) or "no backup yet")
            else:
                print(f"restored: {backup.restore(arguments.name, arguments.into, store)}")
        except backup.BackupError as error:
            print(error, file=sys.stderr)
            return 1
        return 0

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
        case "backup":
            logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
            try:
                settings = backup.settings_from(os.environ)
                store = backup.S3Store(settings)
                if arguments.every:
                    backup.run(url, settings, store, arguments.every)
                print(f"backup written: {backup.backup(url, settings, store, datetime.now(UTC))}")
            except backup.BackupError as error:
                print(error, file=sys.stderr)
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
