from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable

from ..errors import ConfigurationError, SecurityError

_WINDOWS_RESERVED = re.compile(
    r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$", re.IGNORECASE
)


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


class PathGuard:
    """Resolve user-controlled paths under explicit roots without link escapes."""

    def __init__(self, allowed_roots: Iterable[str | os.PathLike[str]]) -> None:
        roots: list[Path] = []
        for raw_root in allowed_roots:
            root = Path(raw_root).expanduser()
            if not root.is_absolute():
                raise ConfigurationError(
                    "ALLOWED_ROOT_NOT_ABSOLUTE", f"Allowed root must be absolute: {root}"
                )
            if not root.exists() or not root.is_dir():
                raise ConfigurationError(
                    "ALLOWED_ROOT_INVALID", f"Allowed root must be an existing directory: {root}"
                )
            if _is_link_or_junction(root):
                raise ConfigurationError(
                    "ALLOWED_ROOT_IS_LINK", f"Allowed root cannot be a link or junction: {root}"
                )
            roots.append(root.resolve(strict=True))
        if not roots:
            raise ConfigurationError("ALLOWED_ROOTS_EMPTY", "At least one allowed root is required")
        self._roots = tuple(roots)

    @property
    def allowed_roots(self) -> tuple[Path, ...]:
        return self._roots

    def resolve(
        self,
        candidate: str | os.PathLike[str],
        *,
        base_root: str | os.PathLike[str] | None = None,
        must_exist: bool = False,
    ) -> Path:
        raw_text = os.fspath(candidate)
        if "\x00" in raw_text:
            raise SecurityError("PATH_INVALID", "Path contains a null byte")
        raw = Path(raw_text).expanduser()
        self._reject_reserved_parts(raw)

        if not raw.is_absolute():
            if base_root is None:
                raise SecurityError("RELATIVE_PATH_WITHOUT_ROOT", "Relative path needs a base root")
            base = Path(base_root).expanduser()
            base_resolved = base.resolve(strict=True)
            containing_root = self._containing_root(base_resolved)
            if containing_root is None:
                raise SecurityError("BASE_ROOT_NOT_ALLOWED", f"Base root is outside allowed roots: {base}")
            self._reject_linked_segments(containing_root, base_resolved)
            raw = base_resolved / raw

        absolute = Path(os.path.abspath(raw))
        resolved = absolute.resolve(strict=False)
        root = self._containing_root(resolved)
        if root is None:
            raise SecurityError("PATH_OUTSIDE_ALLOWED_ROOT", f"Path is outside allowed roots: {candidate}")

        self._reject_linked_segments(root, absolute)
        if must_exist and not resolved.exists():
            raise SecurityError("PATH_NOT_FOUND", f"Path does not exist: {resolved}")
        return resolved

    def _containing_root(self, candidate: Path) -> Path | None:
        for root in self._roots:
            try:
                if os.path.commonpath((os.path.normcase(root), os.path.normcase(candidate))) == os.path.normcase(root):
                    return root
            except ValueError:
                continue
        return None

    @staticmethod
    def _reject_reserved_parts(path: Path) -> None:
        if os.name != "nt":
            return
        for part in path.parts:
            if part == path.anchor:
                continue
            if part in {".", ".."}:
                continue
            if ":" in part:
                raise SecurityError("PATH_ALTERNATE_STREAM", f"Windows alternate streams are forbidden: {part}")
            cleaned = part.rstrip(" .")
            if cleaned != part or _WINDOWS_RESERVED.match(cleaned):
                raise SecurityError("PATH_RESERVED_NAME", f"Unsafe Windows path segment: {part}")

    @staticmethod
    def _reject_linked_segments(root: Path, absolute: Path) -> None:
        try:
            relative = absolute.relative_to(root)
        except ValueError:
            return
        current = root
        for part in relative.parts:
            current = current / part
            if current.exists() and _is_link_or_junction(current):
                raise SecurityError("PATH_LINK_ESCAPE", f"Link or junction is not allowed: {current}")
