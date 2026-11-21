"""request_scaffold tests.

Digest lock: the canonical-JSON digests computed by the service (zero
carto_core dependency) must equal the digests the kernel computed on the same
real E2E materials — values recorded during the verified 2026-11-20 run.
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from conftest import _SERVICE_ROOT
from request_scaffold import request_scaffold

FIXTURES = Path(__file__).parent / "fixtures"

# Kernel-computed digests of the real E2E materials (2026-11-20 run)
KNOWN_DRAFT_DIGEST = "sha256:fbe96d2cb293bb317f7293d7f0d6937883f6a23237924df21347f33d01ae02f2"
KNOWN_REGISTRATION_DIGEST = "sha256:e95c836ea51669022175c2dd0229ca3da9ef2da848fd47cd5cec9e90ec557d18"
KNOWN_TEMPLATE_DIGEST = "sha256:0561399063fbbdb86ee3e35a3de5802850f924cf043fbd9dd06d3e7e28d88962"

IDENTITY = {
    "project_id": "test-project",
    "tenant_id": "test-tenant",
    "subject_id": "test-operator",
    "approver_subject_id": "test-approver",
}


class RequestScaffoldTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        # Mini project: real draft/registration/template index + synthetic assets
        (self.tmp / "data").mkdir()
        shutil.copy(FIXTURES / "draft.json", self.tmp / "data" / "itinerary-draft.json")
        shutil.copy(FIXTURES / "registration.yaml", self.tmp / "registration.yaml")
        shutil.copytree(FIXTURES / "template-repo", self.tmp / "template-repo")
        (self.tmp / "fonts").mkdir()
        (self.tmp / "fonts" / "font.ttf").write_bytes(b"fake-single-face-ttf")
        (self.tmp / "fonts" / "font.otf").write_bytes(b"fake-otf")
        (self.tmp / "basemap.png").write_bytes(b"fake-png-bytes-for-raw-digest")
        self.ctx = {"allowed_root": self.tmp}

    def tearDown(self):
        self._tmp.cleanup()

    def scaffold(self, **overrides):
        args = dict(draft_path="data/itinerary-draft.json", **IDENTITY,
                    font_path="fonts/font.ttf",
                    requested_at="2026-11-20T00:00:00Z")
        args.update(overrides)
        return request_scaffold(args, self.ctx)

    def test_canonical_digests_match_kernel(self):
        result = self.scaffold()
        self.assertEqual(result["status"], "built", result)
        self.assertEqual(result["bound_digests"]["draft"], KNOWN_DRAFT_DIGEST)
        self.assertEqual(result["bound_digests"]["registration"], KNOWN_REGISTRATION_DIGEST)
        self.assertEqual(result["bound_digests"]["template"], KNOWN_TEMPLATE_DIGEST)

    def test_basemap_raw_byte_digest(self):
        import hashlib
        expected = "sha256:" + hashlib.sha256(b"fake-png-bytes-for-raw-digest").hexdigest()
        result = self.scaffold()
        self.assertEqual(result["bound_digests"]["basemap"], expected)

    def test_request_shape(self):
        # idempotency_key must satisfy the 16-128 char validation ("idem-1"
        # was an invalid fixture value the validation rightly rejects).
        result = self.scaffold(request_id="req-1", run_id="run-1",
                               idempotency_key="idempotency-key-0001")
        request = json.loads((self.tmp / "generate-request.yaml").read_text(encoding="utf-8"))
        binding = request["source_bindings"][0]
        self.assertTrue(binding["pending"])
        self.assertEqual(binding["preparation"], "mcp-itinerary-chain")
        self.assertEqual(len(binding["field_bindings"]), 7)
        self.assertEqual(request["template"]["digest"], KNOWN_TEMPLATE_DIGEST)
        self.assertEqual(request["page_layout"],
                         {"model": "fixed-page", "width_mm": 420, "height_mm": 297, "dpi": 200})
        self.assertEqual(request["scope"], "project:test-project")
        self.assertEqual(request["subject"]["approver_subject_id"], "test-approver")
        self.assertEqual(request["requested_at"], "2026-11-20T00:00:00Z")
        self.assertEqual(request["idempotency_key"], "idempotency-key-0001")
        # deterministic identity pinning
        self.assertEqual(request["request_id"], "req-1")
        self.assertEqual(request["run_id"], "run-1")

    def test_identity_required(self):
        result = self.scaffold(project_id="")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "IDENTITY_REQUIRED")

    def test_template_not_published(self):
        index = self.tmp / "template-repo" / "template-index.yaml"
        index.write_text("entries: []\n", encoding="utf-8")
        result = self.scaffold()
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "TEMPLATE_NOT_PUBLISHED")

    def test_font_must_be_ttf(self):
        result = self.scaffold(font_path="fonts/font.ttf")
        self.assertEqual(result["status"], "built")
        result = self.scaffold(font_path="fonts/font.otf")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "FONT_FORMAT_UNSUPPORTED")

    def test_missing_basemap(self):
        result = self.scaffold(basemap_path="nope.png")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "PATH_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
