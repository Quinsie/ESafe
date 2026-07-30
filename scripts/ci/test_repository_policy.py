#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import PurePosixPath

from repository_policy import (
    UPSTAGE_GATE_PATH,
    check_external_ai_source,
    forbidden_path_reason,
    secret_findings,
)


class RepositoryBoundaryTests(unittest.TestCase):
    def test_only_readme_is_an_independent_markdown_document(self) -> None:
        self.assertIsNone(forbidden_path_reason(PurePosixPath("README.md")))
        self.assertIsNotNone(forbidden_path_reason(PurePosixPath("LOCAL_PATCH_README.md")))
        self.assertIsNotNone(forbidden_path_reason(PurePosixPath("docs/execution/STATUS.md")))

    def test_runtime_environment_is_forbidden(self) -> None:
        self.assertIsNone(forbidden_path_reason(PurePosixPath(".env.example")))
        self.assertIsNotNone(forbidden_path_reason(PurePosixPath(".env")))
        self.assertIsNotNone(forbidden_path_reason(PurePosixPath(".env.live")))


class SecretScannerTests(unittest.TestCase):
    def test_placeholders_and_references_are_allowed(self) -> None:
        content = "\n".join(
            (
                "UPSTAGE_API_KEY=CHANGE_ME",
                "POSTGRES_PASSWORD=${POSTGRES_PASSWORD}",
                "secret: <injected-at-runtime>",
            )
        )
        self.assertEqual(secret_findings(PurePosixPath(".env.example"), content), [])

    def test_literal_secret_is_rejected(self) -> None:
        findings = secret_findings(
            PurePosixPath("bad.env"),
            "UPSTAGE_API_KEY=should-not-be-committed",
        )
        self.assertEqual(len(findings), 1)

    def test_private_key_is_rejected(self) -> None:
        findings = secret_findings(
            PurePosixPath("key.txt"),
            "-----BEGIN " + "PRIVATE KEY-----",
        )
        self.assertEqual(len(findings), 1)


class ExternalAiPolicyTests(unittest.TestCase):
    def test_direct_document_ocr_outside_gate_is_rejected(self) -> None:
        source = """
async def send(client, settings):
    key = settings.upstage_api_key
    return await client.post("/document-digitization", files={"document": b"raw"})
"""
        findings = check_external_ai_source(
            PurePosixPath("backend/app/sld_analysis.py"),
            source,
        )
        self.assertEqual(len(findings), 1)
        self.assertIn("direct Upstage endpoint", findings[0])

    def test_client_call_requires_privacy_attestation(self) -> None:
        source = """
async def explain(client):
    return await client.complete_json(user_prompt="payload")
"""
        findings = check_external_ai_source(
            PurePosixPath("backend/app/example.py"),
            source,
        )
        self.assertEqual(len(findings), 1)
        self.assertIn("privacy_verified", findings[0])

    def test_central_gate_must_fail_closed(self) -> None:
        unsafe = """
async def digitize_document(client, privacy_verified):
    return await client.post("/document-digitization")
"""
        findings = check_external_ai_source(UPSTAGE_GATE_PATH, unsafe)
        self.assertEqual(len(findings), 1)
        self.assertIn("fail-closed", findings[0])

    def test_central_gate_with_guard_is_allowed(self) -> None:
        safe = """
async def digitize_document(client, privacy_verified):
    if not privacy_verified:
        raise ValueError("UPSTAGE_PRIVACY_NOT_VERIFIED")
    return await client.post("/document-digitization")
"""
        self.assertEqual(check_external_ai_source(UPSTAGE_GATE_PATH, safe), [])


if __name__ == "__main__":
    unittest.main()
