"""Internal, opt-in worker. Not a second Carto CLI or a production tool gateway.

Only trusted installed Hermes code is loaded. Audit guards reduce accidental
side effects; they are NOT a security sandbox for hostile Python/native code.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sys
from pathlib import Path


class _Discard(io.TextIOBase):
    def write(self, text: str) -> int:
        return len(text)


def _audit(event: str, args: tuple) -> None:
    if event.startswith(("socket.", "subprocess.", "os.spawn", "os.exec")) or event in {
        "os.system", "os.remove", "os.rename", "os.rmdir", "os.mkdir", "os.symlink", "os.link", "os.truncate",
    }:
        raise PermissionError("HOST_PROBE_SIDE_EFFECT_DENIED")
    if event == "open":
        path, mode, flags = args
        if isinstance(path, (str, bytes, os.PathLike)):
            name = Path(os.fsdecode(path)).name.lower()
            if name.startswith(".env") or name in {"auth.json", "auth.lock", ".hermes_history", "state.db"}:
                raise PermissionError("HOST_PROBE_CREDENTIAL_READ_DENIED")
        if (isinstance(mode, str) and any(char in mode for char in "wax+")) or (
            isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        ):
            raise PermissionError("HOST_PROBE_WRITE_DENIED")


def main() -> None:
    result = {
        "status": "failed", "scope": "isolated-skill-resource-read",
        "skill_document_read": False, "resource_read": False,
        "tool_names": [], "code": "HOST_TOOL_READ_FAILED",
    }
    source, home, skill = (Path(item) for item in sys.argv[1:4])
    expected = {}
    for name in ("SKILL.md", "schemas/layout.schema.json"):
        expected[name] = hashlib.sha256((skill / name).read_text(encoding="utf-8").encode("utf-8")).hexdigest()
    os.environ["HERMES_HOME"] = str(home)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(source))
    sys.addaudithook(_audit)
    try:
        with contextlib.redirect_stdout(_Discard()), contextlib.redirect_stderr(_Discard()):
            from tools.skills_tool import skill_view
            for relative, field in (("SKILL.md", "skill_document_read"), ("schemas/layout.schema.json", "resource_read")):
                # Linked-file mode avoids credential-readiness checks and inline
                # shell preprocessing. Do not invoke full skill setup here.
                value = json.loads(skill_view("carto-agent", file_path=relative, task_id="carto-host-preflight", preprocess=False))
                content = value.get("content")
                source_path = value.get("_source_path")
                result[field] = bool(value.get("success") is True and isinstance(content, str)
                                     and isinstance(source_path, str)
                                     and Path(source_path).resolve() == (skill / relative).resolve()
                                     and hashlib.sha256(content.encode("utf-8")).hexdigest() == expected[relative])
            result["tool_names"] = ["skill_view"]
            if result["skill_document_read"] and result["resource_read"]:
                result.update(status="passed", code="LOCAL_RESOURCE_READ_VERIFIED")
    except BaseException:
        # Never emit foreign tracebacks/config values or captured tool content.
        result["code"] = "HOST_RUNTIME_INTERFACE_UNAVAILABLE"
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
