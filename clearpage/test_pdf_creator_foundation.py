"""Offline PDF creator configuration checks; no PDF or model execution."""

import unittest
from pathlib import Path

from runtime_controls import agent_instructions


ROOT = Path(__file__).resolve().parent.parent


class PdfCreatorFoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.instructions = agent_instructions(ROOT, "pdf_creator")
        cls.contract = (ROOT / "clearpage/agents/pdf_creator/OUTPUT_CONTRACT.md").read_text(encoding="utf-8")

    def test_requires_separate_production_handoff(self):
        self.assertIn("trusted production-handoff authorization", self.instructions)
        self.assertIn("READY_FOR_PRODUCTION_REVIEW` alone is insufficient", self.instructions)
        self.assertIn("no separate production handoff -> BLOCKED", self.contract)

    def test_does_not_allow_creator_to_release_product(self):
        self.assertIn("quality_approved`: always false", self.contract)
        self.assertIn("commercial_release_allowed`: always false", self.contract)
        self.assertIn("independent Quality Auditor", self.instructions)

    def test_requires_all_page_visual_checks(self):
        self.assertIn("render **every page**", self.instructions)
        self.assertIn("sha256", self.contract)
        self.assertIn("requirement_coverage", self.contract)


if __name__ == "__main__":
    unittest.main()
