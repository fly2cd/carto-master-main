"""Path guard tests: the --allowed-root boundary for file-touching tools."""
import tempfile
import unittest
from pathlib import Path

from conftest import _SERVICE_ROOT
from _service_utils import ServiceError, resolve_under_root


class PathGuardTests(unittest.TestCase):
    def test_relative_resolves_against_root(self):
        resolved = resolve_under_root("tests/fixtures/draft.json", _SERVICE_ROOT,
                                      must_exist=True)
        self.assertTrue(resolved.is_absolute())
        self.assertEqual(resolved.name, "draft.json")

    def test_absolute_inside_root_allowed(self):
        target = _SERVICE_ROOT / "geocode.py"
        self.assertEqual(resolve_under_root(str(target), _SERVICE_ROOT, must_exist=True),
                         target)

    def test_absolute_outside_root_refused(self):
        with self.assertRaises(ServiceError) as caught:
            resolve_under_root("C:/Windows/win.ini", _SERVICE_ROOT)
        self.assertEqual(caught.exception.code, "PATH_OUTSIDE_ROOT")

    def test_escape_via_dotdot_refused(self):
        with self.assertRaises(ServiceError) as caught:
            resolve_under_root("../../etc/passwd", _SERVICE_ROOT)
        self.assertEqual(caught.exception.code, "PATH_OUTSIDE_ROOT")

    def test_missing_with_must_exist(self):
        with self.assertRaises(ServiceError) as caught:
            resolve_under_root("no/such/file.json", _SERVICE_ROOT, must_exist=True)
        self.assertEqual(caught.exception.code, "PATH_NOT_FOUND")

    def test_missing_without_must_exist_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            resolved = resolve_under_root("out/new.json", Path(tmp))
            self.assertEqual(resolved, Path(tmp).resolve() / "out" / "new.json")


if __name__ == "__main__":
    unittest.main()
