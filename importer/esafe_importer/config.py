from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ImportConfig:
    database_url: str
    import_id: str
    source_root: Path
    boundary_root: Path
    source_manifest: dict[str, Any]
    verified_manifest: dict[str, Any]
    boundary_manifest: dict[str, Any]

    @classmethod
    def from_environment(cls) -> ImportConfig:
        database_url = required_environment("DATABASE_URL")
        import_id = required_environment("REFERENCE_IMPORT_ID")
        reference_root = Path(os.getenv("REFERENCE_ROOT", "/reference"))
        boundary_snapshot = required_environment("ADMIN_BOUNDARY_SNAPSHOT")
        source_root = reference_root / "imports" / import_id
        boundary_root = reference_root / "acquired" / boundary_snapshot
        source_manifest = read_json(source_root / "source-manifest.json")
        verified_manifest = read_json(source_root / "verified-manifest.json")
        boundary_manifest = read_json(boundary_root / "manifest.json")
        config = cls(
            database_url=database_url,
            import_id=import_id,
            source_root=source_root,
            boundary_root=boundary_root,
            source_manifest=source_manifest,
            verified_manifest=verified_manifest,
            boundary_manifest=boundary_manifest,
        )
        config.validate_manifests()
        return config

    @property
    def source_manifest_hash(self) -> str:
        return str(self.verified_manifest["sourceManifestSha256"])

    @property
    def boundary_manifest_hash(self) -> str:
        return sha256_file(self.boundary_root / "manifest.json")

    def validate_manifests(self) -> None:
        source_manifest_path = self.source_root / "source-manifest.json"
        if self.source_manifest.get("importId") != self.import_id:
            raise ValueError("source manifest import ID mismatch")
        if self.verified_manifest.get("importId") != self.import_id:
            raise ValueError("verified manifest import ID mismatch")
        if self.verified_manifest.get("verified") is not True:
            raise ValueError("source manifest is not verified")
        expected_source_hash = str(self.verified_manifest.get("sourceManifestSha256", ""))
        if sha256_file(source_manifest_path) != expected_source_hash:
            raise ValueError("source manifest SHA-256 mismatch")
        if self.source_manifest.get("fileCount") != self.verified_manifest.get("fileCount"):
            raise ValueError("source manifest file count mismatch")
        if self.source_manifest.get("totalBytes") != self.verified_manifest.get("totalBytes"):
            raise ValueError("source manifest byte count mismatch")
        boundary_files = self.boundary_manifest.get("files", [])
        if len(boundary_files) != 1:
            raise ValueError("boundary manifest must contain one GeoJSON file")
        boundary_file = self.boundary_root / str(boundary_files[0]["path"])
        if sha256_file(boundary_file) != boundary_files[0].get("sha256"):
            raise ValueError("boundary GeoJSON SHA-256 mismatch")


def required_environment(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"required environment variable is missing: {name}")
    return value


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
