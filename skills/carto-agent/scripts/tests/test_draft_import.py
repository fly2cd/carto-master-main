# -*- coding: utf-8 -*-
"""A->B deferred publication import tests (design §8.4, plan §5.2 延后保存 A→B).

Proves a finished creation run A (validated-draft) is imported into a NEW publication run B
by immutable draft/evidence digest binding; B re-authors under its own final identity,
re-validates and publishes through the reused chain; A is never modified. Fail-closed guards:
missing source binding, evidence/draft/design drift, unfinished source, run mismatch.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import yaml

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.canonical import sha256_digest
from carto_core.errors import ProtocolError
from carto_core.schema_registry import SchemaRegistry
from carto_core.workflow.segment_workflow import create_template_workflow
from carto_core.scenarios.general_thematic.raster import style_contract
from tests.fixtures.schema_cases import VALID_CASES
from tests.test_general_thematic import sign, APPROVAL_KEY, KEY


class DraftImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="draft-import-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.project = self.tmp / "project"
        self.project.mkdir()
        self.registry = SchemaRegistry()
        self.design = style_contract()

    def _request(self, request_id, template_id="seg-style", version="1.0.0", design=None):
        req = deepcopy(VALID_CASES["segment-create-request"])
        req["request_id"] = request_id
        req["template_id"] = template_id
        req["version"] = version
        req["design"] = deepcopy(self.design if design is None else design)
        req["targets"] = ["pdf", "png"]
        req["subject"]["environment"] = "local"
        return req

    def _write(self, name, doc):
        path = self.project / name
        path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return path

    def _workflow(self, workdir):
        return create_template_workflow("map-style", allowed_roots=[self.tmp],
                                        project_root=self.project, workdir=workdir, registry=self.registry)

    def _run_creation_A(self):
        req = self._request("seg-request-one")
        rp = self._write("request-a.yaml", req)
        wf = self._workflow("work-a")
        wf.analyze(rp)
        wf.brief(rp)
        wf.author(rp)
        result = wf.validate(rp, attestation_key=KEY)
        self.assertEqual("validated-draft", result["result_kind"])
        self.assertEqual(("succeeded", "validate"), (result["state"]["status"], result["state"]["step"]))
        return req, result

    def _binding(self, req):
        evidence_uri = "work-a/validation/segment-validation-evidence.yaml"
        evidence = yaml.safe_load((self.project / evidence_uri).read_text(encoding="utf-8"))
        return {"source_run_id": req["request_id"], "source_run_uri": "work-a",
                "source_draft_digest": sha256_digest(req["design"]),
                "source_evidence_digest": evidence["evidence_digest"],
                "source_evidence_uri": evidence_uri}

    def _pub_request(self, req):
        pub = {"schema_version": 1, "publication_request_id": f"pubreq-{req['request_id']}",
               "request_id": req["request_id"], "kind": req["kind"], "intent_state": "ready",
               "target": {"repository_scope": "local:templates", "namespace": req["namespace"],
                          "template_id": req["template_id"], "version": req["version"]}}
        return self._write(f"pub-{req['request_id']}.yaml", pub)

    def test_import_binds_finished_A_and_B_publishes_A_unchanged(self):
        req_a, _ = self._run_creation_A()
        a_state = (self.project / "work-a/job-state.json").read_bytes()
        a_evidence = (self.project / "work-a/validation/segment-validation-evidence.yaml").read_bytes()
        req_b = self._request("seg-publish-b")
        req_b["source_import"] = self._binding(req_a)
        rp_b = self._write("request-b.yaml", req_b)
        wf_b = self._workflow("work-b")
        imported = wf_b.import_draft(rp_b)
        self.assertEqual(("pending", "author"), (imported["state"]["status"], imported["state"]["step"]))
        self.assertEqual(req_a["request_id"], imported["import_record"]["source_run_id"])
        wf_b.author(rp_b)
        validated = wf_b.validate(rp_b, attestation_key=KEY, publication_request=self._pub_request(req_b))
        self.assertEqual("ready-to-publish", validated["result_kind"])
        repo_root = self.tmp / "repo"
        prepared = wf_b.prepare_publication(rp_b, repository_root=repo_root,
                                            repository_scope="local:templates",
                                            idempotency_key="seg-import-publish-0001")
        tp = sign("TP", "approve-template-publish", "template-publication", prepared["object_digest"],
                  subject_id=req_b["subject"]["approver_subject_id"], scope=req_b["scope"],
                  tenant_id=req_b["subject"]["tenant_id"])
        tp_path = self._write("tp-b.yaml", asdict(tp))
        result = wf_b.publish(rp_b, tp_path, repository_root=repo_root,
                              repository_scope="local:templates", idempotency_key="seg-import-publish-0001",
                              approval_key=APPROVAL_KEY, renderer_attestation_key=KEY)
        self.assertEqual("succeeded", result["state"]["status"])
        self.assertTrue((repo_root / "packages/local/map-style/seg-style/1.0.0/manifest.yaml").is_file())
        # A is byte-identical after B's full publication chain.
        self.assertEqual(a_state, (self.project / "work-a/job-state.json").read_bytes())
        self.assertEqual(a_evidence, (self.project / "work-a/validation/segment-validation-evidence.yaml").read_bytes())

    def test_import_requires_source_binding(self):
        self._run_creation_A()
        req_b = self._request("seg-publish-b")  # no source_import
        rp_b = self._write("request-b.yaml", req_b)
        with self.assertRaisesRegex(ProtocolError, "IMPORT_SOURCE_REQUIRED"):
            self._workflow("work-b").import_draft(rp_b)

    def test_import_evidence_digest_mismatch_fails_closed(self):
        req_a, _ = self._run_creation_A()
        req_b = self._request("seg-publish-b")
        binding = self._binding(req_a)
        binding["source_evidence_digest"] = "sha256:" + "f" * 64
        req_b["source_import"] = binding
        rp_b = self._write("request-b.yaml", req_b)
        with self.assertRaisesRegex(ProtocolError, "IMPORT_EVIDENCE_DRIFT"):
            self._workflow("work-b").import_draft(rp_b)

    def test_import_design_drift_fails_closed(self):
        req_a, _ = self._run_creation_A()
        req_b = self._request("seg-publish-b")
        req_b["source_import"] = self._binding(req_a)
        req_b["design"]["typography"]["title_pt"] = 20  # schema-valid but != A draft content (18)
        rp_b = self._write("request-b.yaml", req_b)
        with self.assertRaisesRegex(ProtocolError, "IMPORT_DESIGN_DRIFT"):
            self._workflow("work-b").import_draft(rp_b)

    def test_import_source_run_mismatch_fails_closed(self):
        req_a, _ = self._run_creation_A()
        req_b = self._request("seg-publish-b")
        binding = self._binding(req_a)
        binding["source_run_id"] = "another-run"
        req_b["source_import"] = binding
        rp_b = self._write("request-b.yaml", req_b)
        with self.assertRaisesRegex(ProtocolError, "IMPORT_SOURCE_RUN_MISMATCH"):
            self._workflow("work-b").import_draft(rp_b)

    def test_import_unfinished_source_fails_closed(self):
        req_a = self._request("seg-request-one")
        rp_a = self._write("request-a.yaml", req_a)
        wf_a = self._workflow("work-a")
        wf_a.analyze(rp_a)  # A stops at pending/brief, not a finished draft
        req_b = self._request("seg-publish-b")
        req_b["source_import"] = {
            "source_run_id": req_a["request_id"], "source_run_uri": "work-a",
            "source_draft_digest": sha256_digest(req_a["design"]),
            "source_evidence_digest": "sha256:" + "0" * 64,
            "source_evidence_uri": "work-a/validation/segment-validation-evidence.yaml"}
        rp_b = self._write("request-b.yaml", req_b)
        with self.assertRaisesRegex(ProtocolError, "IMPORT_SOURCE_NOT_FINISHED"):
            self._workflow("work-b").import_draft(rp_b)


if __name__ == "__main__":
    unittest.main()