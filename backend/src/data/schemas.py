"""Phase 1.2 — the one unified schema every data source conforms to.

Every loader (DVMCP, MCPTox, benign, custom) emits this exact shape so nothing
downstream needs to know which source a case came from.
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel

Source = Literal["dvmcp", "mcptox", "benign", "custom"]
GroundTruth = Literal["clean", "malicious"]


class ToolTestCase(BaseModel):
    case_id: str                          # unique across all sources, e.g. "dvmcp-ch2-t1"
    source: Source
    tool_name: str
    tool_description: str
    tool_schema: dict                     # raw JSON schema of the tool's parameters
    sample_response: Optional[str] = None  # populated only for runtime/response cases
    ground_truth_label: GroundTruth
    attack_category: Optional[str] = None  # e.g. "tool_poisoning", "rug_pull", "tool_shadowing"

    # ------------------------------------------------------------------ scope --
    def requested_scope(self) -> Optional[str]:
        """The sensitive scope this tool's PARAMETER SCHEMA actually grants, or None.

        Phase 12.7 — schema-based. The earlier rule substring-matched the whole
        description ("upload", "write", "token", ...), so prose that merely *mentioned*
        a capability escalated benign tools (benign FPR 3.3% -> 17.3%). This rule
        asks what the caller can actually DO through the parameters:

          credential_access  a parameter that takes a secret (password, token, api key, ...)
          code_execution     a parameter that is code/a command (code, command, script, ...)
          network_egress     a parameter that names an outbound destination (url, host,
                             endpoint, webhook, recipient, ...)
          filesystem_write   a path-like parameter together with write intent: a write-verb
                             tool name, a content/data parameter, a mode/action enum or
                             boolean flag (write, delete, overwrite, ...)

        Prose in the description is never consulted. The old keyword rule is kept as
        ``requested_scope_keyword()`` for before/after comparison only.
        """
        params = _schema_params(self.tool_schema)
        if not params:
            return None
        names = {n.lower() for n in params}
        if names & _CRED_PARAMS or any(_CRED_SUBSTR.search(n) for n in names):
            return "credential_access"
        if names & _EXEC_PARAMS or _enum_values(params) & _EXEC_ENUMS:
            return "code_execution"
        if names & _EGRESS_PARAMS or any(
                (p or {}).get("format") in ("uri", "url", "hostname") for p in params.values()):
            return "network_egress"
        tool_verb = re.split(r"[_\-\s]", self.tool_name.lower())[0] if self.tool_name else ""
        if names & _PATH_PARAMS:
            if (tool_verb in _WRITE_VERBS or names & _CONTENT_PARAMS or names & _WRITE_FLAGS
                    or _enum_values(params) & _WRITE_ENUMS):
                return "filesystem_write"
        elif tool_verb in _WRITE_VERBS and names & _WEAK_PATH_PARAMS:
            return "filesystem_write"
        return None

    def requested_scope_keyword(self) -> Optional[str]:
        """The ORIGINAL keyword rule (substring match over name + description +
        schema). Kept only so reports can show the before/after effect of the
        schema-based rule on the same data; nothing in the pipeline calls it."""
        blob = (self.tool_name + " " + self.tool_description + " " + str(self.tool_schema)).lower()
        if any(k in blob for k in ("password", "token", "secret", "credential", "api_key", "id_rsa", ".ssh")):
            return "credential_access"
        if any(k in blob for k in ("exec", "subprocess", "shell", "eval(", "os.system", "run_command")):
            return "code_execution"
        if any(k in blob for k in ("http://", "https://", "requests.", "urllib", "socket", "egress", "upload", "send_to")):
            return "network_egress"
        if any(k in blob for k in (
            "write", "overwrite", "delete", "unlink", "rename", "save", "modify",
            "read+write", "read/write", "'w'", '"w"', "'rw'", '"rw"', "/etc/", "delete_file",
        )):
            return "filesystem_write"
        return None


# --- schema vocabulary for requested_scope() --------------------------------------
_CRED_PARAMS = {"password", "passwd", "pwd", "secret", "token", "access_token", "refresh_token",
                "auth_token", "api_key", "apikey", "private_key", "credentials", "credential",
                "client_secret", "bearer", "passphrase", "session_token"}
_CRED_SUBSTR = re.compile(r"(password|secret|api_?key|private_?key|access_?token)")
_EXEC_PARAMS = {"code", "command", "cmd", "script", "shell", "shell_command", "bash", "powershell",
                "python_code", "exec", "sql_script"}
_EXEC_ENUMS = {"shell", "exec", "execute", "eval", "bash", "powershell"}
_EGRESS_PARAMS = {"url", "uri", "endpoint", "webhook", "webhook_url", "callback_url", "host",
                  "hostname", "server_url", "base_url", "destination_url", "recipient",
                  "recipients", "to", "cc", "bcc", "email_to"}
_PATH_PARAMS = {"path", "filepath", "file_path", "filename", "file", "file_name", "dir",
                "directory", "folder", "paths", "src", "dst", "output_path", "save_path"}
# Ambiguous names ("target" may be a language, "source" a URL): only path-like when
# the tool NAME is itself a write verb (move_file(source, destination)).
_WEAK_PATH_PARAMS = {"destination", "dest", "source", "target"}
_CONTENT_PARAMS = {"content", "contents", "data", "body", "edits", "text", "payload"}
_WRITE_FLAGS = {"overwrite", "recursive", "force", "append", "truncate"}
_WRITE_VERBS = {"write", "create", "delete", "remove", "move", "rename", "edit", "save", "copy",
                "mkdir", "append", "overwrite", "update", "put", "patch", "rm", "touch", "chmod",
                "upload", "replace"}
_WRITE_ENUMS = {"w", "rw", "write", "delete", "remove", "overwrite", "append", "create", "move",
                "rename", "update"}


def _schema_params(schema: dict) -> dict:
    """The ``properties`` of a JSON-schema-ish dict (tolerates a few wrappers)."""
    if not isinstance(schema, dict):
        return {}
    props = schema.get("properties")
    if props is None and isinstance(schema.get("raw"), dict):
        props = schema["raw"].get("properties")
    return props if isinstance(props, dict) else {}


def _enum_values(params: dict) -> set:
    out: set = set()
    for p in params.values():
        if isinstance(p, dict):
            for v in p.get("enum") or []:
                out.add(str(v).lower())
    return out
