"""Phase 1.2 — the one unified schema every data source conforms to.

Every loader (DVMCP, MCPTox, benign, custom) emits this exact shape so nothing
downstream needs to know which source a case came from.
"""
from __future__ import annotations

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

    def requested_scope(self) -> Optional[str]:
        """Best-effort inference of the sensitive scope a tool's schema requests,
        used by the Phase 6 enforcement layer. Returns one of the allowlist scope
        names or None. Heuristic — deliberately conservative (over-flags rather
        than under-flags sensitive scopes)."""
        blob = (self.tool_name + " " + self.tool_description + " " + str(self.tool_schema)).lower()
        if any(k in blob for k in ("password", "token", "secret", "credential", "api_key", "id_rsa", ".ssh")):
            return "credential_access"
        if any(k in blob for k in ("exec", "subprocess", "shell", "eval(", "os.system", "run_command")):
            return "code_execution"
        if any(k in blob for k in ("http://", "https://", "requests.", "urllib", "socket", "egress", "upload", "send_to")):
            return "network_egress"
        if any(k in blob for k in ("open(", "write", "path", "filename", "filesystem", "/etc/", "delete_file")):
            return "filesystem_write"
        return None
