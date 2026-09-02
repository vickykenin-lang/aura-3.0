import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class ApprovalDashboardContractTests(unittest.TestCase):
    def test_dashboard_is_aura3_native(self):
        text = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn("const REPO='vickykenin-lang/aura-3.0'", text)
        self.assertIn('AURA3 Founder Approval Center', text)
        self.assertNotIn('vickykenin-lang/design-infra-aura2', text)
        self.assertNotIn('AURA2 — Command Dashboard', text)

    def test_dashboard_uses_founder_issue_commands(self):
        text = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn("doCommand('APPROVE'", text)
        self.assertIn("doCommand('REJECT'", text)
        self.assertIn('/issues/new?title=', text)

    def test_dashboard_reads_canonical_state(self):
        text = (ROOT / 'index.html').read_text(encoding='utf-8')
        for path in ['content/calendar.json', 'data/gate_results.json', 'data/approvals.json', 'content/published.json', 'evaluation/AURA3_FINAL_COMPLETION_STATUS.json']:
            self.assertIn(path, text)

    def test_workflow_is_founder_gated_and_strict(self):
        text = (ROOT / '.github/workflows/aura3-founder-approval.yml').read_text(encoding='utf-8')
        self.assertIn("github.event.issue.user.login == github.repository_owner", text)
        self.assertIn('python3 scripts/approve_manual.py', text)
        self.assertIn('published post cannot be retroactively rejected', text)
        self.assertIn('permissions:', text)
        self.assertIn('issues: write', text)


if __name__ == '__main__':
    unittest.main()
