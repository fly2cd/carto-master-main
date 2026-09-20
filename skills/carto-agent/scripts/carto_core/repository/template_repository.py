from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ..canonical import sha256_digest
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry, load_document
from ..security.paths import PathGuard

REPOSITORY_VERSION = "1.0.0"
VALIDATION_VERSION = "1.0.0"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_yaml(path: Path, value: dict[str, Any], *, replace: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not replace and path.exists():
        existing = load_document(path)
        if existing != value:
            raise ProtocolError("IMMUTABLE_ARTIFACT_CONFLICT", str(path))
        return
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            yaml.safe_dump(value, stream, allow_unicode=True, sort_keys=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        temporary = Path(temporary_name)
        if temporary.exists():
            temporary.unlink()


class _RepositoryLock:
    def __init__(self, path: Path, timeout_seconds: float = 10.0) -> None:
        self.path = path
        self.timeout_seconds = timeout_seconds
        self.fd: int | None = None

    def __enter__(self) -> "_RepositoryLock":
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, f"{os.getpid()}\n".encode("ascii"))
                return self
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise ProtocolError("REPOSITORY_LOCK_TIMEOUT", str(self.path))
                time.sleep(0.05)

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


class TemplateRepository:
    """Index-authoritative immutable repository for exact template versions."""

    def __init__(self, *, path_guard: PathGuard, root: str | Path,
                 repository_scope: str, registry: SchemaRegistry | None = None) -> None:
        self.path_guard = path_guard
        self.root = path_guard.resolve(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.repository_scope = repository_scope
        self.registry = registry or SchemaRegistry()
        self.index_path = self.root / "template-index.yaml"
        self.lock_path = self.root / ".publish.lock"
        self._load_index()

    def lookup_idempotency(self, idempotency_key: str, *, package_digest: str,
                           evidence_digest: str) -> dict[str, Any] | None:
        path = self._transaction_path(idempotency_key)
        if not path.is_file():
            return None
        receipt = load_document(path)
        self.registry.validate("publication-receipt", receipt)
        if (receipt["idempotency_key"] != idempotency_key
                or receipt["package_ref"]["digest"] != package_digest
                or receipt["evidence_ref"]["digest"] != evidence_digest
                or receipt["repository_scope"] != self.repository_scope):
            raise ProtocolError("IDEMPOTENCY_CONFLICT", idempotency_key)
        entry = self._find_entry(self._load_index(), receipt["package_ref"], receipt.get("namespace"))
        if entry is None or entry["publication_receipt_path"] != path.relative_to(self.root).as_posix():
            raise ProtocolError("PUBLICATION_TRANSACTION_INCOMPLETE", idempotency_key)
        return receipt

    def load_publication_approval(self, publication: dict[str, Any]) -> dict[str, Any]:
        """Read and authenticate the approval retained by an immutable publication transaction."""
        self.registry.validate("publication-receipt", publication)
        reference = publication["approval_ref"]
        uri = Path(reference["uri"])
        if uri.is_absolute() or ".." in uri.parts:
            raise ProtocolError("PUBLICATION_APPROVAL_REF_INVALID", reference["uri"])
        path = self.path_guard.resolve(self.root / uri, must_exist=True)
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ProtocolError("PUBLICATION_APPROVAL_REF_INVALID", reference["uri"]) from exc
        approval = load_document(path)
        if not isinstance(approval, dict):
            raise ProtocolError("PUBLICATION_APPROVAL_INVALID", reference["uri"])
        self.registry.validate("approval-receipt", approval)
        if sha256_digest(approval) != reference["digest"]:
            raise ProtocolError("PUBLICATION_APPROVAL_DRIFT", reference["uri"])
        return approval

    def publish(self, *, package_root: Path, snapshot: dict[str, Any], evidence: dict[str, Any],
                approval: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        package_root = self.path_guard.resolve(package_root, must_exist=True)
        if not package_root.is_dir():
            raise ProtocolError("STAGING_PACKAGE_MISSING", str(package_root))
        with _RepositoryLock(self.lock_path):
            prior = self.lookup_idempotency(
                idempotency_key, package_digest=snapshot["package_digest"],
                evidence_digest=evidence["evidence_digest"],
            )
            if prior is not None:
                return prior
            index = self._load_index()
            package = snapshot["manifest"]["package"]
            identity_ref = {"kind": package["kind"], "id": package["id"],
                            "version": package["version"], "digest": snapshot["package_digest"]}
            existing = self._find_entry(index, identity_ref, package["namespace"])
            if existing is not None:
                if existing["digest"] != snapshot["package_digest"]:
                    raise ProtocolError("VERSION_CONFLICT", f"{package['namespace']}:{package['kind']}:{package['id']}@{package['version']}")
                raise ProtocolError("VERSION_ALREADY_PUBLISHED", package["id"])

            relative_package = Path("packages") / package["namespace"] / package["kind"] / package["id"] / package["version"]
            destination = self.root / relative_package
            self._persist_package(package_root, destination, snapshot)
            evidence_path = self.root / "evidence" / f"{evidence['evidence_digest'][7:]}.yaml"
            approval_digest = sha256_digest(approval)
            approval_path = self.root / "approvals" / f"{approval_digest[7:]}.yaml"
            _atomic_yaml(evidence_path, evidence, replace=False)
            _atomic_yaml(approval_path, approval, replace=False)

            published_at = _now()
            receipt_path = self._transaction_path(idempotency_key)
            entry = {
                "namespace": package["namespace"], "kind": package["kind"],
                "id": package["id"], "version": package["version"],
                "digest": snapshot["package_digest"],
                "manifest_path": (relative_package / "manifest.yaml").as_posix(),
                "manifest_digest": snapshot["manifest_digest"],
                "evidence_digest": evidence["evidence_digest"],
                "publication_receipt_path": receipt_path.relative_to(self.root).as_posix(),
                "status": "published", "published_at": published_at,
            }
            before_digest = index["digest"]
            updated_entries = sorted([*index["entries"], entry],
                                     key=lambda item: (item["namespace"], item["kind"], item["id"], item["version"]))
            new_index = {
                "schema_version": 1, "index_id": "local-template-index", "version": REPOSITORY_VERSION,
                "repository_scope": self.repository_scope, "entries": updated_entries,
                "generated_at": published_at,
            }
            new_index["digest"] = sha256_digest(new_index)
            self.registry.validate("template-index", new_index)
            receipt = {
                "schema_version": 1,
                "receipt_id": f"publication-{hashlib.sha256(idempotency_key.encode('utf-8')).hexdigest()[:20]}",
                "namespace": package["namespace"],
                "package_ref": identity_ref,
                "manifest_digest": snapshot["manifest_digest"],
                "evidence_ref": {"id": "template-validation-evidence", "version": VALIDATION_VERSION,
                                 "digest": evidence["evidence_digest"],
                                 "uri": evidence_path.relative_to(self.root).as_posix()},
                "dependency_lock_ref": {"id": "dependency-lock", "version": package["version"],
                                        "digest": snapshot["dependency_lock_digest"],
                                        "uri": (relative_package / snapshot["manifest"]["dependency_lock"]).as_posix()},
                "index_digest_before": before_digest, "index_digest_after": new_index["digest"],
                "repository_scope": self.repository_scope,
                "approval_ref": {"id": "publication-approval", "version": "1.0.0",
                                 "digest": approval_digest, "uri": approval_path.relative_to(self.root).as_posix()},
                "published_at": published_at, "idempotency_key": idempotency_key,
            }
            self.registry.validate("publication-receipt", receipt)
            _atomic_yaml(receipt_path, receipt, replace=False)
            _atomic_yaml(self.index_path, new_index)
            read_back = self._load_index()
            if read_back["digest"] != new_index["digest"] or self._find_entry(read_back, identity_ref, package["namespace"]) is None:
                raise ProtocolError("INDEX_COMMIT_VERIFICATION_FAILED", package["id"])
            return receipt

    def discover(self, *, namespace: str, kind: str, template_id: str,
                 version: str) -> dict[str, Any]:
        if not all((namespace, kind, template_id, version)):
            raise ProtocolError("EXACT_TEMPLATE_REF_REQUIRED", "namespace, kind, id and version are required")
        reference = {"kind": kind, "id": template_id, "version": version, "digest": ""}
        entry = self._find_entry(self._load_index(), reference, namespace, ignore_digest=True)
        if entry is None:
            raise ProtocolError("TEMPLATE_NOT_INDEXED", f"{namespace}:{kind}:{template_id}@{version}")
        manifest = self.path_guard.resolve(self.root / entry["manifest_path"], must_exist=True)
        self._verify_package_tree(manifest.parent, entry["digest"], entry["manifest_digest"], published=True)
        return entry

    def _load_index(self) -> dict[str, Any]:
        if not self.index_path.exists():
            value = {"schema_version": 1, "index_id": "local-template-index",
                     "version": REPOSITORY_VERSION, "repository_scope": self.repository_scope,
                     "entries": [], "generated_at": "1970-01-01T00:00:00Z"}
            value["digest"] = sha256_digest(value)
            self.registry.validate("template-index", value)
            return value
        value = load_document(self.index_path)
        self.registry.validate("template-index", value)
        body = dict(value)
        supplied = body.pop("digest")
        if sha256_digest(body) != supplied:
            raise ProtocolError("TEMPLATE_INDEX_DIGEST_MISMATCH", str(self.index_path))
        if value["repository_scope"] != self.repository_scope:
            raise ProtocolError("REPOSITORY_SCOPE_MISMATCH", value["repository_scope"])
        identities = [(item["namespace"], item["kind"], item["id"], item["version"])
                      for item in value["entries"]]
        if len(identities) != len(set(identities)):
            raise ProtocolError("TEMPLATE_INDEX_DUPLICATE_IDENTITY", str(self.index_path))
        return value

    @staticmethod
    def _find_entry(index: dict[str, Any], reference: dict[str, Any], namespace: str | None,
                    ignore_digest: bool = False) -> dict[str, Any] | None:
        for entry in index["entries"]:
            if (entry["namespace"], entry["kind"], entry["id"], entry["version"]) == (
                    namespace, reference["kind"], reference["id"], reference["version"]):
                if not ignore_digest and reference.get("digest") and entry["digest"] != reference["digest"]:
                    return entry
                return entry
        return None

    def _persist_package(self, source: Path, destination: Path, snapshot: dict[str, Any]) -> None:
        linked = [path.relative_to(source).as_posix() for path in source.rglob("*")
                  if path.is_symlink()]
        if linked:
            raise ProtocolError("PACKAGE_LINK_FORBIDDEN", linked[0])
        if destination.exists():
            checksum = destination / "checksums.sha256"
            if checksum.is_file() and _file_digest(checksum) == snapshot["package_digest"]:
                return
            raise ProtocolError("REPOSITORY_RESIDUE_CONFLICT", str(destination))
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".package-", dir=destination.parent))
        try:
            shutil.copytree(source, temporary / "content", symlinks=True)
            content = temporary / "content"
            self._verify_package_tree(
                content, snapshot["package_digest"], snapshot["manifest_digest"], published=False,
            )
            os.replace(content, destination)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def _verify_package_tree(self, root: Path, package_digest: str,
                             manifest_digest: str, *, published: bool) -> None:
        checksum_path = root / "checksums.sha256"
        manifest_path = root / "manifest.yaml"
        error_code = "PUBLISHED_PACKAGE_CORRUPT" if published else "PACKAGE_READ_BACK_FAILED"
        if not checksum_path.is_file() or not manifest_path.is_file():
            raise ProtocolError(error_code, str(root))
        if _file_digest(checksum_path) != package_digest:
            raise ProtocolError(error_code, str(checksum_path))
        if _file_digest(manifest_path) != manifest_digest:
            code = "PUBLISHED_MANIFEST_CORRUPT" if published else error_code
            raise ProtocolError(code, str(manifest_path))
        tree_paths = list(root.rglob("*"))
        linked = [path.relative_to(root).as_posix() for path in tree_paths if path.is_symlink()]
        if linked:
            raise ProtocolError(error_code, f"symbolic link is forbidden: {linked[0]}")
        recorded: dict[str, str] = {}
        for line in checksum_path.read_text(encoding="utf-8").splitlines():
            parts = line.split("  ", 1)
            if len(parts) != 2 or len(parts[0]) != 64:
                raise ProtocolError(error_code, "invalid checksum record")
            relative = Path(parts[1])
            if relative.is_absolute() or ".." in relative.parts or "\\" in parts[1]:
                raise ProtocolError(error_code, parts[1])
            if parts[1] in recorded:
                raise ProtocolError(error_code, parts[1])
            recorded[parts[1]] = "sha256:" + parts[0]
        actual = sorted(path.relative_to(root).as_posix() for path in tree_paths if path.is_file())
        if actual != sorted(["checksums.sha256", *recorded]):
            raise ProtocolError(error_code, str(root))
        for relative, digest in recorded.items():
            if _file_digest(root / relative) != digest:
                raise ProtocolError(error_code, relative)
        manifest = load_document(manifest_path)
        self.registry.validate("manifest", manifest)
        if sorted(recorded) != sorted(["manifest.yaml", *manifest["files"]]):
            raise ProtocolError(error_code, "manifest/checksum file set mismatch")
        if any(recorded.get(relative) != digest for relative, digest in manifest["checksums"].items()):
            raise ProtocolError(error_code, "manifest/checksum digest mismatch")

    def _transaction_path(self, idempotency_key: str) -> Path:
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        return self.root / "transactions" / f"{digest}.yaml"

