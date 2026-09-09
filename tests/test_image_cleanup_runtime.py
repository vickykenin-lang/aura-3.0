import os, sys, unittest
from unittest import mock
sys.path.insert(0,'scripts')
import aura3_image_cleanup_runtime as c

class CleanupTests(unittest.TestCase):
    def test_cleanup_candidate(self):
        self.assertTrue(c._cleanup_candidate({'visual_ok':False,'quality':8,'design_freshness':'Current','copyright_status':'Clear','watermarks':'Present','brand_logo_risk':'None'}))
        self.assertTrue(c._cleanup_candidate({'visual_ok':False,'quality':8,'design_freshness':'Current','copyright_status':'Unknown','watermarks':'None','brand_logo_risk':'Present'}))
    def test_flagged_or_dated_not_cleaned(self):
        self.assertFalse(c._cleanup_candidate({'visual_ok':False,'quality':9,'design_freshness':'Current','copyright_status':'Flagged','watermarks':'Present'}))
        self.assertFalse(c._cleanup_candidate({'visual_ok':False,'quality':9,'design_freshness':'Dated','copyright_status':'Clear','watermarks':'Present'}))
    def test_secret_required(self):
        with mock.patch.dict(os.environ,{},clear=True):
            with self.assertRaises(RuntimeError): c._json_request('https://api.dev.runwayml.com/v1/tasks/test')
    def test_https_required(self):
        with self.assertRaises(ValueError): c.cleanup_image('http://example.com/a.jpg')

if __name__=='__main__': unittest.main()
