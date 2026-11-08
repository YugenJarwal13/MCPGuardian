"""Credential leaks in a tool reply: the DVMCP token-theft case is a reply with a key and a JWT and no instruction."""
from __future__ import annotations

import asyncio

from src.security import secret_scan as ss

LEAK = """Service Status: EmailPro API
- API Key: epro_api_5f4e3d2c1b0a9z8y7x
- Access Token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkFDTUUgQ29ycCJ9.5TxfEAVbZRGbKnXaL9Lrx9NqXSNFw2ac4FDzPHvRzSQ
"""


def test_finds_and_redacts_credentials():
    kinds = {f.kind for f in ss.scan(LEAK)}
    assert {"JSON web token", "secret value"} <= kinds
    red = ss.redact_text(LEAK)
    assert "epro_api_5f4e3d2c1b0a9z8y7x" not in red and "eyJhbGciOiJIUzI1NiIs" not in red


def test_ordinary_text_is_not_flagged():
    for ok in ("Inbox (3 messages): Subject: Password reset request",
               "The password field must be at least 8 characters.",
               "Status: Active. Token Expiration: 2025-12-31",
               "Quarterly revenue grew 4%."):
        assert ss.scan(ok) == [], ok


def test_runtime_check_raises_a_clean_reply_with_a_leak_to_suspicious_and_escalates():
    from src.adk_layer.callbacks.enforcement_callbacks import GuardianDecision, combine_verdicts
    from src.config import allowlist
    from src.evaluation.ablation_config import AblationConfig
    from src.mcp_gateway.interceptor import GuardianInterceptor

    it = GuardianInterceptor(ablation=AblationConfig(), use_llm=False)
    verdict, *_ = asyncio.run(it.inspect_response_runtime("check_service_status", LEAK))
    assert verdict.verdict == "suspicious" and "Credential scan" in verdict.reasoning
    assert all("epro_api_5f4e" not in p or "…" in p for p in verdict.flagged_phrases)
    assert combine_verdicts(None, verdict, False, None, allowlist()) == GuardianDecision.ESCALATE
