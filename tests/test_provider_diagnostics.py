import json
from pathlib import Path
import sys
import unittest
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from provider_diagnostics import safe_failure


class SafeFailureTests(unittest.TestCase):
    def test_underlying_http_status_is_retained_without_url_or_secret(self):
        cause = HTTPError('https://provider.invalid/?access_token=DO_NOT_LOG', 403, 'secret=DO_NOT_LOG', {}, None)
        outer = RuntimeError('provider rejected token DO_NOT_LOG')
        outer.__cause__ = cause
        value = safe_failure(outer, 'legacy_visual_revalidation')
        self.assertEqual(value['http_status'], 403)
        self.assertEqual(value['category'], 'AUTH_OR_ACCESS')
        self.assertNotIn('DO_NOT_LOG', json.dumps(value))
        self.assertNotIn('provider.invalid', json.dumps(value))

    def test_runtime_http_code_is_extracted_without_raw_text(self):
        self.assertEqual(safe_failure(RuntimeError('DeepSeek HTTP 429 token=PRIVATE'), 'provider_preflight')['category'], 'RATE_LIMIT')

    def test_billing_and_timeout_are_classified(self):
        self.assertEqual(safe_failure(RuntimeError('dunning decision is deny PRIVATE'), 'provider_preflight')['category'], 'BILLING')
        self.assertEqual(safe_failure(TimeoutError('PRIVATE'), 'provider_preflight')['category'], 'NETWORK')

    def test_unknown_failure_does_not_invent_a_provider_cause(self):
        value = safe_failure(RuntimeError('PRIVATE'), 'legacy_visual_revalidation')
        self.assertIsNone(value['http_status'])
        self.assertEqual(value['category'], 'PROVIDER_OR_RUNTIME')
        self.assertFalse(value['raw_exception_recorded'])


if __name__ == '__main__':
    unittest.main()
