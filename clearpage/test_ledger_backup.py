"""Backup never overwrites snapshots and always passes SQLite integrity."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from ledger_backup import backup_ledger
from runtime_controls import RunLedger


class LedgerBackupTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.ledger_path = root / 'runs.sqlite'
        self.destination = root / 'snapshot.sqlite'
        self.ledger = RunLedger(self.ledger_path)

    def test_backup_preserves_checkpoint_and_reopens_after_restart(self):
        self.ledger.reserve('run-1')
        self.ledger.checkpoint('run-1', research_task_id=42)
        result = backup_ledger(self.ledger_path, self.destination)
        self.assertEqual(result['runs'], 1)
        self.assertEqual(result['integrity'], 'ok')
        restored = RunLedger(self.destination)
        self.assertEqual(restored.status('run-1'), 'RESERVED')
        self.assertEqual(restored.task_ids('run-1'), (42, None))
        # Subsequent writes to the original cannot alter the snapshot.
        self.ledger.reserve('run-2')
        self.assertIsNone(restored.status('run-2'))

    def test_never_overwrites_existing_backup(self):
        self.ledger.reserve('run-1')
        backup_ledger(self.ledger_path, self.destination)
        with self.assertRaises(FileExistsError):
            backup_ledger(self.ledger_path, self.destination)
        self.assertEqual(RunLedger(self.destination).status('run-1'), 'RESERVED')

    def test_missing_source_and_same_source_destination_denied(self):
        with self.assertRaises(ValueError):
            backup_ledger(self.ledger_path.parent / 'missing.sqlite', self.destination)
        with self.assertRaises(ValueError):
            backup_ledger(self.ledger_path, self.ledger_path)

    def test_corrupt_database_rejected_and_no_output_created(self):
        corrupted = self.ledger_path.parent / 'corrupt.sqlite'
        corrupted.write_bytes(b'not sqlite')
        with self.assertRaises(sqlite3.DatabaseError):
            backup_ledger(corrupted, self.destination)
        self.assertFalse(self.destination.exists())


if __name__ == '__main__':
    unittest.main()
