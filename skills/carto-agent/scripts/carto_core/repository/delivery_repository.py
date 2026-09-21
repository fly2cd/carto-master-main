from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import yaml

from ..canonical import sha256_digest
from ..errors import ProtocolError, SecurityError
from ..schema_registry import SchemaRegistry, load_document
from ..security.paths import PathGuard
from ..workflow.map_data_preparation import file_digest

FailureHook = Callable[[str], None]
_PACKAGE_FILES = {"map.pdf", "map.png", "README.md", "delivery-manifest.yaml", "checksums.sha256"}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _atomic_yaml(path: Path, value: dict[str, Any], *, immutable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if immutable and path.exists():
        existing = load_document(path)
        if existing != value:
            raise ProtocolError("IMMUTABLE_ARTIFACT_CONFLICT", str(path))
        return
    fd, name = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            yaml.safe_dump(value, stream, allow_unicode=True, sort_keys=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        temporary = Path(name)
        if temporary.exists():
            temporary.unlink()


class _DeliveryLock:
    def __init__(self, path: Path, timeout: float = 10.0) -> None:
        self.path = path
        self.timeout = timeout
        self.fd: int | None = None

    def __enter__(self) -> "_DeliveryLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, f"{os.getpid()}\n".encode("ascii"))
                return self
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise ProtocolError("DELIVERY_TRANSACTION_LOCKED", str(self.path))
                time.sleep(0.05)

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.fd is not None:
            os.close(self.fd)
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


class DeliveryRepository:
    """Project-local journal for recoverable, atomically visible delivery packages."""

    def __init__(self, *, path_guard: PathGuard, project_root: Path, work_root: Path,
                 registry: SchemaRegistry | None = None) -> None:
        self.path_guard = path_guard
        self.project_root = project_root
        self.work_root = work_root
        self.registry = registry or SchemaRegistry()
        self.root = self.path_guard.resolve(project_root / ".carto" / "delivery")
        self.transactions_root = self.root / "transactions"
        self.receipts_root = self.root / "receipts"
        self.locks_root = self.root / "locks"

    def deliver(self, *, manifest: dict[str, Any], manifest_ref: dict[str, str],
                approval_ref: dict[str, str], failure_hook: FailureHook | None = None) -> dict[str, Any]:
        self.registry.validate("delivery-manifest", manifest)
        manifest_digest = sha256_digest(manifest)
        if manifest_ref.get("digest") != manifest_digest:
            raise ProtocolError("DELIVERY_MANIFEST_REFERENCE_MISMATCH", manifest["manifest_id"])
        key_hash = hashlib.sha256(manifest["idempotency_key"].encode("utf-8")).hexdigest()
        transaction_path = self.transactions_root / f"{key_hash}.yaml"
        lock_path = self.locks_root / f"{key_hash}.lock"
        with _DeliveryLock(lock_path):
            transaction = self._load_or_create_transaction(
                transaction_path, manifest, manifest_ref, approval_ref
            )
            if failure_hook and transaction["status"] == "intent-created":
                failure_hook("after-transaction-intent")
            receipt_path = self.receipts_root / f"{transaction['delivery_id']}.yaml"
            if receipt_path.exists():
                receipt = self._load_receipt(receipt_path, transaction)
                self._verify_package(self.project_root / transaction["final_path"], manifest)
                transaction = self._mark_receipt_written(transaction_path, transaction, receipt, receipt_path)
                return self._result(transaction, receipt, transaction_path, receipt_path, True)

            final_path = self.path_guard.resolve(
                transaction["final_path"], base_root=self.project_root
            )
            staging_path = self.path_guard.resolve(
                transaction["staging_path"], base_root=self.project_root
            )
            self._validate_destination(final_path, staging_path)
            if final_path.exists():
                self._verify_package(final_path, manifest)
                transaction = self._mark_committed(transaction_path, transaction)
            else:
                if staging_path.exists():
                    try:
                        self._verify_package(staging_path, manifest)
                    except (ProtocolError, SecurityError, OSError):
                        self._remove_staging(staging_path)
                if not staging_path.exists():
                    self._write_staging(staging_path, manifest)
                self._verify_package(staging_path, manifest)
                transaction = self._update(
                    transaction_path, transaction, status="staged", phase="commit"
                )
                if failure_hook:
                    failure_hook("after-staging")
                final_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.replace(staging_path, final_path)
                except OSError as exc:
                    if final_path.exists():
                        self._verify_package(final_path, manifest)
                        self._remove_staging(staging_path)
                    else:
                        raise ProtocolError("DELIVERY_ATOMIC_COMMIT_FAILED", str(final_path)) from exc
                self._verify_package(final_path, manifest)
                transaction = self._mark_committed(transaction_path, transaction)
                if failure_hook:
                    failure_hook("after-atomic-commit")

            receipt = self._build_receipt(transaction, manifest, manifest_ref, approval_ref)
            self.registry.validate("delivery-receipt", receipt)
            _atomic_yaml(receipt_path, receipt, immutable=True)
            if failure_hook:
                failure_hook("after-receipt")
            transaction = self._mark_receipt_written(transaction_path, transaction, receipt, receipt_path)
            return self._result(transaction, receipt, transaction_path, receipt_path, False)

    @staticmethod
    def _result(transaction: dict[str, Any], receipt: dict[str, Any], transaction_path: Path,
                receipt_path: Path, replay: bool) -> dict[str, Any]:
        return {
            "transaction": transaction,
            "receipt": receipt,
            "transaction_path": transaction_path,
            "receipt_path": receipt_path,
            "idempotent_replay": replay,
        }

    def lookup(self, idempotency_key: str) -> dict[str, Any] | None:
        key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        path = self.transactions_root / f"{key_hash}.yaml"
        if not path.is_file():
            return None
        transaction = load_document(path)
        if not isinstance(transaction, dict):
            raise ProtocolError("DELIVERY_TRANSACTION_INVALID", str(path))
        self.registry.validate("delivery-transaction", transaction)
        if transaction["idempotency_key"] != idempotency_key:
            raise ProtocolError("IDEMPOTENCY_CONFLICT", idempotency_key)
        result: dict[str, Any] = {"transaction": transaction}
        if "receipt_ref" in transaction:
            receipt_path = self.path_guard.resolve(transaction["receipt_ref"]["uri"], must_exist=True)
            result["receipt"] = self._load_receipt(receipt_path, transaction)
        return result

    def lookup_delivery(self, delivery_id: str) -> dict[str, Any] | None:
        receipt_path = self.receipts_root / f"{delivery_id}.yaml"
        if not receipt_path.is_file():
            return None
        receipt = load_document(receipt_path)
        if not isinstance(receipt, dict):
            raise ProtocolError("DELIVERY_RECEIPT_INVALID", str(receipt_path))
        self.registry.validate("delivery-receipt", receipt)
        if receipt["delivery_id"] != delivery_id:
            raise ProtocolError("DELIVERY_RECEIPT_BINDING_MISMATCH", delivery_id)
        result = self.lookup(receipt["idempotency_key"])
        if result is None or result.get("receipt") != receipt:
            raise ProtocolError("DELIVERY_RECEIPT_BINDING_MISMATCH", delivery_id)
        return result

    def _load_or_create_transaction(self, path: Path, manifest: dict[str, Any],
                                    manifest_ref: dict[str, str], approval_ref: dict[str, str]) -> dict[str, Any]:
        manifest_digest = sha256_digest(manifest)
        if path.exists():
            value = load_document(path)
            if not isinstance(value, dict):
                raise ProtocolError("DELIVERY_TRANSACTION_INVALID", str(path))
            self.registry.validate("delivery-transaction", value)
            expected = (
                manifest["idempotency_key"], manifest_digest, manifest["recipient"],
                manifest["destination"], manifest["project_id"], manifest["tenant_id"], manifest["run_id"],
            )
            actual = (
                value["idempotency_key"], value["manifest_digest"], value["recipient"],
                value["destination"], value["project_id"], value["tenant_id"], value["run_id"],
            )
            if actual != expected:
                raise ProtocolError("IDEMPOTENCY_CONFLICT", manifest["idempotency_key"])
            if value["manifest_ref"] != manifest_ref or value["approval_ref"] != approval_ref:
                raise ProtocolError("DELIVERY_TRANSACTION_BINDING_CONFLICT", value["transaction_id"])
            return value
        suffix = manifest_digest[7:23]
        transaction_id = f"delivery-transaction-{suffix}"
        delivery_id = f"delivery-{suffix}"
        final_relative = manifest["destination"]["relative_path"]
        final = Path(final_relative)
        staging_relative = (final.parent / f".{final.name}.staging-{suffix}").as_posix()
        now = _now()
        transaction = {
            "schema_version": 1,
            "transaction_id": transaction_id,
            "delivery_id": delivery_id,
            "project_id": manifest["project_id"],
            "tenant_id": manifest["tenant_id"],
            "run_id": manifest["run_id"],
            "manifest_ref": manifest_ref,
            "manifest_digest": manifest_digest,
            "idempotency_key": manifest["idempotency_key"],
            "recipient": manifest["recipient"],
            "destination": manifest["destination"],
            "staging_path": staging_relative,
            "final_path": final_relative,
            "approval_ref": approval_ref,
            "status": "intent-created",
            "phase": "staging",
            "artifacts": self._package_artifacts(manifest),
            "created_at": now,
            "updated_at": now,
        }
        self.registry.validate("delivery-transaction", transaction)
        _atomic_yaml(path, transaction, immutable=True)
        return transaction

    def _validate_destination(self, final_path: Path, staging_path: Path) -> None:
        if final_path == self.project_root or final_path == staging_path:
            raise SecurityError("DELIVERY_DESTINATION_INVALID", str(final_path))
        for protected in (self.root, self.work_root):
            try:
                final_path.relative_to(protected)
                raise SecurityError("DELIVERY_DESTINATION_PROTECTED", str(final_path))
            except ValueError:
                pass
        if final_path.exists() and (final_path.is_symlink() or getattr(final_path, "is_junction", lambda: False)()):
            raise SecurityError("DELIVERY_DESTINATION_LINK_FORBIDDEN", str(final_path))

    def _write_staging(self, staging: Path, manifest: dict[str, Any]) -> None:
        staging.parent.mkdir(parents=True, exist_ok=True)
        staging.mkdir()
        try:
            for item in manifest["artifacts"]:
                source = self.path_guard.resolve(item["path"], base_root=self.project_root, must_exist=True)
                if not source.is_file() or source.is_symlink():
                    raise SecurityError("DELIVERY_ARTIFACT_INVALID", str(source))
                if file_digest(source) != item["digest"] or source.stat().st_size != item["size_bytes"]:
                    raise ProtocolError("DELIVERY_ARTIFACT_DRIFT", item["path"])
                shutil.copyfile(source, staging / f"map.{item['format']}")
            _atomic_yaml(staging / "delivery-manifest.yaml", manifest)
            readme = self._readme(manifest)
            (staging / "README.md").write_text(readme, encoding="utf-8", newline="\n")
            checksummed = ["README.md", "delivery-manifest.yaml", "map.pdf", "map.png"]
            lines = [f"{file_digest(staging / name)[7:]}  {name}" for name in checksummed]
            (staging / "checksums.sha256").write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")
        except OSError as exc:
            self._remove_staging(staging)
            raise ProtocolError("DELIVERY_STAGING_WRITE_FAILED", str(staging)) from exc
        except Exception:
            self._remove_staging(staging)
            raise

    def _verify_package(self, root: Path, manifest: dict[str, Any]) -> None:
        if not root.is_dir() or root.is_symlink() or getattr(root, "is_junction", lambda: False)():
            raise ProtocolError("DELIVERY_PACKAGE_INVALID", str(root))
        tree = list(root.rglob("*"))
        if any(path.is_symlink() or getattr(path, "is_junction", lambda: False)() for path in tree):
            raise SecurityError("DELIVERY_PACKAGE_LINK_FORBIDDEN", str(root))
        files = {path.relative_to(root).as_posix() for path in tree if path.is_file()}
        if files != _PACKAGE_FILES:
            raise ProtocolError("DELIVERY_PACKAGE_FILE_SET_MISMATCH", str(root))
        packaged_manifest = load_document(root / "delivery-manifest.yaml")
        if packaged_manifest != manifest:
            raise ProtocolError("DELIVERY_PACKAGE_MANIFEST_DRIFT", str(root))
        recorded: dict[str, str] = {}
        for line in (root / "checksums.sha256").read_text(encoding="ascii").splitlines():
            parts = line.split("  ", 1)
            if len(parts) != 2 or len(parts[0]) != 64 or parts[1] in recorded:
                raise ProtocolError("DELIVERY_PACKAGE_CHECKSUM_INVALID", str(root))
            recorded[parts[1]] = "sha256:" + parts[0]
        if set(recorded) != _PACKAGE_FILES - {"checksums.sha256"}:
            raise ProtocolError("DELIVERY_PACKAGE_CHECKSUM_INVALID", str(root))
        if any(file_digest(root / name) != digest for name, digest in recorded.items()):
            raise ProtocolError("DELIVERY_PACKAGE_DIGEST_MISMATCH", str(root))
        for item in manifest["artifacts"]:
            target = root / f"map.{item['format']}"
            if file_digest(target) != item["digest"] or target.stat().st_size != item["size_bytes"]:
                raise ProtocolError("DELIVERY_ARTIFACT_DRIFT", item["path"])
        notice = "合成数据演示，非真实风险研判"
        readme = (root / "README.md").read_text(encoding="utf-8")
        if notice not in readme or any(value not in readme for value in manifest["licenses"] + manifest["limitations"]):
            raise ProtocolError("DELIVERY_LIMITATIONS_MISSING", str(root))

    def _build_receipt(self, transaction: dict[str, Any], manifest: dict[str, Any],
                       manifest_ref: dict[str, str], approval_ref: dict[str, str]) -> dict[str, Any]:
        delivered_at = transaction.get("committed_at") or _now()
        return {
            "schema_version": 1,
            "receipt_id": f"delivery-receipt-{transaction['delivery_id'][9:]}",
            "delivery_id": transaction["delivery_id"],
            "transaction_id": transaction["transaction_id"],
            "manifest_ref": manifest_ref,
            "manifest_digest": sha256_digest(manifest),
            "idempotency_key": manifest["idempotency_key"],
            "final_path": transaction["final_path"],
            "artifacts": transaction["artifacts"],
            "g3_approval_ref": approval_ref,
            "status": "committed",
            "delivered_at": delivered_at,
        }

    def _load_receipt(self, path: Path, transaction: dict[str, Any]) -> dict[str, Any]:
        value = load_document(path)
        if not isinstance(value, dict):
            raise ProtocolError("DELIVERY_RECEIPT_INVALID", str(path))
        self.registry.validate("delivery-receipt", value)
        expected = (
            transaction["delivery_id"], transaction["transaction_id"], transaction["manifest_digest"],
            transaction["idempotency_key"], transaction["final_path"], transaction["approval_ref"],
            transaction["artifacts"],
        )
        actual = (
            value["delivery_id"], value["transaction_id"], value["manifest_digest"],
            value["idempotency_key"], value["final_path"], value["g3_approval_ref"], value["artifacts"],
        )
        if actual != expected:
            raise ProtocolError("DELIVERY_RECEIPT_BINDING_MISMATCH", transaction["transaction_id"])
        return value

    def _mark_committed(self, path: Path, transaction: dict[str, Any]) -> dict[str, Any]:
        if transaction["status"] in {"committed", "receipt-written"}:
            return transaction
        return self._update(path, transaction, status="committed", phase="receipt", committed_at=_now())

    def _mark_receipt_written(self, path: Path, transaction: dict[str, Any], receipt: dict[str, Any],
                              receipt_path: Path) -> dict[str, Any]:
        receipt_ref = {
            "id": receipt["receipt_id"], "version": "1.0.0",
            "digest": sha256_digest(receipt), "uri": str(receipt_path),
        }
        if transaction["status"] == "receipt-written":
            if transaction.get("receipt_ref") != receipt_ref:
                raise ProtocolError("DELIVERY_TRANSACTION_RECEIPT_DRIFT", transaction["transaction_id"])
            return transaction
        return self._update(
            path, transaction, status="receipt-written", phase="receipt", receipt_ref=receipt_ref
        )

    def _update(self, path: Path, transaction: dict[str, Any], **changes: Any) -> dict[str, Any]:
        updated = {**transaction, **changes, "updated_at": _now()}
        self.registry.validate("delivery-transaction", updated)
        _atomic_yaml(path, updated)
        return updated

    @staticmethod
    def _package_artifacts(manifest: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {"path": f"map.{item['format']}", "format": item["format"],
             "digest": item["digest"], "size_bytes": item["size_bytes"]}
            for item in sorted(manifest["artifacts"], key=lambda value: value["format"])
        ]

    @staticmethod
    def _readme(manifest: dict[str, Any]) -> str:
        licenses = "\n".join(f"- {item}" for item in manifest["licenses"])
        limitations = "\n".join(f"- {item}" for item in manifest["limitations"])
        recipient = manifest["recipient"]
        return (
            "# Carto Agent 本地演示交付包\n\n"
            f"接收方：{recipient['recipient_type']} / {recipient['recipient_id']}\n\n"
            "## 许可\n" + licenses + "\n\n"
            "## 限制\n" + limitations + "\n\n"
            "本包仅用于合成数据工程演示，不代表生产制图或真实风险研判能力。\n"
        )

    @staticmethod
    def _remove_staging(path: Path) -> None:
        if path.exists():
            shutil.rmtree(path)

