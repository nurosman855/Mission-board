"""Safe, offline SQLite snapshot for ClearPage worker run ledgers.

Never overwrites an existing destination. Uses SQLite's online backup API to
preserve transaction consistency even while another process holds the ledger.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import tempfile
from pathlib import Path


def backup_ledger(source: Path, destination: Path) -> dict:
    source, destination = Path(source).resolve(), Path(destination).absolute()
    if not source.is_file() or not destination.parent.is_dir() or source == destination:
        raise ValueError('Backup requires an existing source and destination directory')
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('Backup destination already exists')
    fd, temp_name = tempfile.mkstemp(prefix='.clearpage-backup-', suffix='.sqlite', dir=destination.parent)
    os.close(fd)
    temp = Path(temp_name)
    try:
        os.chmod(temp, 0o600)
        with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as original:
            with sqlite3.connect(temp) as copy:
                original.backup(copy)
                rows = copy.execute('PRAGMA integrity_check').fetchall()
                if rows != [('ok',)]:
                    raise ValueError('Snapshot failed integrity check')
                count = copy.execute('SELECT COUNT(*) FROM runs').fetchone()[0]
        # Exclusive publish: link() fails if another writer created the target.
        # The backup and target are in the same directory/filesystem.
        os.link(temp, destination)
        return {'backup': str(destination), 'runs': count, 'integrity': 'ok'}
    finally:
        temp.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Create non-overwriting ClearPage SQLite backup')
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = backup_ledger(args.source, args.destination)
    except (OSError, sqlite3.Error, ValueError) as error:
        parser.exit(1, f'Backup denied: {type(error).__name__}\n')
    print(f"Backup verified: {result['runs']} runs, integrity {result['integrity']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
