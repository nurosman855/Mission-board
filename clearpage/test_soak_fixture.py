"""Soak runner must never silently target a nonlocal or unscoped environment."""

import tempfile
import unittest
from pathlib import Path

from soak_fixture import run_probe, role_environment


class SoakFixtureSafetyTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.ledger = Path(directory.name) / 'probe.sqlite'
        self.keys = {'schedule': 'coordinator-only', 'research': 'research-only',
                     'validation': 'validator-only'}

    def test_rejects_external_server(self):
        for target in ('https://real-shop.example', 'http://127.0.0.1:3000@evil.example',
                       'http://localhost:3000@evil.example', 'http://127.0.0.1:3000/path'):
            with self.subTest(target=target), self.assertRaises(ValueError):
                run_probe(runs=1, ledger_path=self.ledger, base_url=target, keys=self.keys)

    def test_rejects_shared_or_missing_credentials(self):
        for keys in ({**self.keys, 'research': 'coordinator-only'},
                     {**self.keys, 'research': ''}, {'schedule': 'admin'}):
            with self.subTest(keys=sorted(keys)):
                with self.assertRaises(ValueError):
                    run_probe(runs=1, ledger_path=self.ledger, base_url='http://127.0.0.1:3000', keys=keys)

    def test_bounds_number_of_runs(self):
        for runs in (0, 101):
            with self.assertRaises(ValueError):
                run_probe(runs=runs, ledger_path=self.ledger,
                          base_url='http://127.0.0.1:3000', keys=self.keys)

    def test_child_environment_never_inherits_other_agent_keys(self):
        parent = {'MC_API_KEY': 'old', 'MC_COORDINATOR_API_KEY': 'coordinator',
                  'MC_RESEARCH_API_KEY': 'research', 'MC_VALIDATION_API_KEY': 'validator',
                  'PATH': '/bin'}
        isolated = role_environment(parent, key='research', base_url='http://127.0.0.1:3000')
        self.assertEqual(isolated['MC_API_KEY'], 'research')
        self.assertEqual(isolated['PATH'], '/bin')
        for name in ('MC_COORDINATOR_API_KEY', 'MC_RESEARCH_API_KEY', 'MC_VALIDATION_API_KEY'):
            self.assertNotIn(name, isolated)


if __name__ == '__main__':
    unittest.main()
