from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from ..canonical import sha256_digest
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry, load_document
from ..security.paths import PathGuard
from .template_repository import TemplateRepository, _file_digest


class ProjectTemplateInstaller:
    """Installs one exact published template into a project-private immutable directory."""

    def __init__(self, *, path_guard: PathGuard, project_root: Path,
                 repository: TemplateRepository, registry: SchemaRegistry | None = None) -> None:
        self.path_guard = path_guard
        self.project_root = path_guard.resolve(project_root, must_exist=True)
        self.repository = repository
        self.registry = registry or SchemaRegistry()

    def install(self, reference: dict[str, Any]) -> dict[str, Any]:
        for key in ("namespace", "kind", "id", "version"):
            if not reference.get(key):
                raise ProtocolError("EXACT_TEMPLATE_REF_REQUIRED", key)
        entry = self.repository.discover(
            namespace=reference["namespace"], kind=reference["kind"],
            template_id=reference["id"], version=reference["version"],
        )
        if reference.get("digest") and reference["digest"] != entry["digest"]:
            raise ProtocolError("TEMPLATE_DIGEST_MISMATCH", reference["id"])
        source_manifest = self.path_guard.resolve(
            self.repository.root / entry["manifest_path"], must_exist=True,
        )
        source = source_manifest.parent
        destination = self.path_guard.resolve(
            self.project_root / ".carto/templates/installed" / reference["namespace"]
            / reference["kind"] / reference["id"] / reference["version"]
        )
        if destination.exists():
            self._verify(destination, entry)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = Path(tempfile.mkdtemp(prefix=".install-", dir=destination.parent))
            try:
                content = temporary / "content"
                shutil.copytree(source, content, symlinks=True)
                linked = [item for item in content.rglob("*") if item.is_symlink()]
                if linked:
                    raise ProtocolError("TEMPLATE_INSTALL_LINK_FORBIDDEN", linked[0].as_posix())
                self._verify(content, entry)
                os.replace(content, destination)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        manifest = load_document(destination / "manifest.yaml")
        return {
            "schema_version": 1,
            "installation_id": f"installed-{reference['id']}-{reference['version'].replace('.', '-')}",
            "template_ref": {"kind": entry["kind"], "id": entry["id"],
                             "version": entry["version"], "digest": entry["digest"]},
            "namespace": entry["namespace"],
            "manifest_digest": entry["manifest_digest"],
            "package_path": destination.as_posix(),
            "contract_digest": sha256_digest({
                name: manifest["checksums"][path]
                for name, path in manifest["business_contracts"].items()
            }),
        }

    def _verify(self, root: Path, entry: dict[str, Any]) -> None:
        manifest_path = root / "manifest.yaml"
        checksum_path = root / "checksums.sha256"
        if not manifest_path.is_file() or not checksum_path.is_file():
            raise ProtocolError("TEMPLATE_INSTALL_INCOMPLETE", str(root))
        if _file_digest(manifest_path) != entry["manifest_digest"]:
            raise ProtocolError("TEMPLATE_INSTALL_MANIFEST_DRIFT", str(root))
        if _file_digest(checksum_path) != entry["digest"]:
            raise ProtocolError("TEMPLATE_INSTALL_PACKAGE_DRIFT", str(root))
        manifest = load_document(manifest_path)
        self.registry.validate("manifest", manifest)
        expected = sorted(["manifest.yaml", "checksums.sha256", *manifest["files"]])
        actual = sorted(item.relative_to(root).as_posix() for item in root.rglob("*") if item.is_file())
        if expected != actual:
            raise ProtocolError("TEMPLATE_INSTALL_FILE_SET_DRIFT", str(root))
        for relative, digest in manifest["checksums"].items():
            if _file_digest(root / relative) != digest:
                raise ProtocolError("TEMPLATE_INSTALL_FILE_DRIFT", relative)
