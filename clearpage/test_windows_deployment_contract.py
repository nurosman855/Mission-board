"""Portable static safeguards; NOT a substitute for executing PowerShell on Windows."""

import unittest
from pathlib import Path


class WindowsDeploymentContractTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / 'windows'
        self.save = (self.root / 'Save-ScopedKey.ps1').read_text(encoding='utf-8')
        self.worker = (self.root / 'Start-ScopedWorker.ps1').read_text(encoding='utf-8')

    def test_keys_are_entered_securely_and_encrypted_for_windows_user(self):
        self.assertIn('Read-Host', self.save)
        self.assertIn('-AsSecureString', self.save)
        self.assertIn('ConvertFrom-SecureString', self.save)
        self.assertIn('LOCALAPPDATA', self.save)
        self.assertIn('already exists for this role', self.save)

    def test_launcher_uses_one_scoped_key_and_restores_process_environment(self):
        self.assertIn('ConvertTo-SecureString', self.worker)
        self.assertIn('ClearPageDigital\\Secrets\\$Role.dpapi', self.worker)
        self.assertIn("'MC_API_KEY', $priorKey", self.worker)
        self.assertIn('MC_RESEARCH_PACKET_PATH', self.worker)
        self.assertIn('finally {', self.worker)
        self.assertIn("[ValidateSet('research', 'validation', 'monitor')]", self.worker)

    def test_launcher_does_not_force_restart_or_change_execution_policy(self):
        for unsafe in ('Register-ScheduledTask', 'Set-ExecutionPolicy', 'Restart-Service',
                       'Invoke-Expression', 'Start-Process -Verb RunAs'):
            self.assertNotIn(unsafe, self.worker)
            self.assertNotIn(unsafe, self.save)


if __name__ == '__main__':
    unittest.main()
