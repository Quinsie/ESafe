from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shapely import wkb
from shapely.geometry import mapping

from esafe_importer.config import read_json
from esafe_importer.sources import normalize_multipolygon

SOURCE_NAME = "국토교통부 국토지리정보원_공간정보공동활용_읍면동"
SOURCE_URL = "https://www.data.go.kr/data/15123128/fileData.do"
SOURCE_VERSION = "2025-11-20"
CSV_SHA256 = "1f0e72e138db32da17cb0029658b42e337fc187187ed0fac81995ea56aa1bcbd"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def build_collection(base_path: Path, csv_path: Path) -> dict[str, Any]:
    if sha256_file(csv_path) != CSV_SHA256:
        raise ValueError("official EMD CSV SHA-256 mismatch")
    collection = read_json(base_path)
    base_features = collection.get("features")
    if not isinstance(base_features, list):
        raise ValueError("base boundary GeoJSON has no feature list")
    parent_names = {
        str(feature["properties"]["region_code"]): str(feature["properties"]["full_name"])
        for feature in base_features
        if feature["properties"].get("level") == "SIGUNGU"
    }
    features = list(base_features)
    seen = {str(feature["properties"]["region_code"]) for feature in features}
    csv.field_size_limit(sys.maxsize)
    with csv_path.open(encoding="cp949", newline="") as stream:
        reader = csv.DictReader(stream)
        expected = {
            "공간정보일렬번호",
            "읍면동코드",
            "읍면동명",
            "객체시군구코드",
            "오브젝트아이디",
            "공간정보",
        }
        if set(reader.fieldnames or ()) != expected:
            raise ValueError("official EMD CSV header mismatch")
        for row in reader:
            region_code = row["읍면동코드"].strip()
            parent_code = row["객체시군구코드"].strip()
            if parent_code not in parent_names:
                continue
            if region_code in seen:
                raise ValueError(f"duplicate admin region: {region_code}")
            geometry, repaired = normalize_multipolygon(
                wkb.loads(row["공간정보"].strip(), hex=True)
            )
            if repaired:
                raise ValueError(f"official EMD geometry required repair: {region_code}")
            name = row["읍면동명"].strip()
            features.append(
                {
                    "type": "Feature",
                    "id": region_code,
                    "properties": {
                        "region_code": region_code,
                        "level": "EUPMYEONDONG",
                        "name": name,
                        "full_name": f"{parent_names[parent_code]} {name}",
                        "parent_code": parent_code,
                        "source": SOURCE_NAME,
                        "source_version": SOURCE_VERSION,
                        "source_metadata": {
                            "source_url": SOURCE_URL,
                            "source_csv_sha256": CSV_SHA256,
                            "serial_number": row["공간정보일렬번호"].strip(),
                            "object_id": row["오브젝트아이디"].strip(),
                            "coordinate_system": "EPSG:4326",
                        },
                    },
                    "geometry": mapping(geometry),
                }
            )
            seen.add(region_code)
    emd_count = len(features) - len(base_features)
    if emd_count < 300:
        raise ValueError(f"unexpected Gwangju/Jeonnam EMD count: {emd_count}")
    return {"type": "FeatureCollection", "features": features}


def write_snapshot(
    collection: dict[str, Any],
    output_root: Path,
    snapshot_id: str,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=False)
    geojson_path = output_root / "admin_regions.geojson"
    with geojson_path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(collection, stream, ensure_ascii=False, separators=(",", ":"))
        stream.write("\n")
    manifest = {
        "snapshot_id": snapshot_id,
        "created_at": datetime.now(UTC).isoformat(),
        "source": "OpenStreetMap base + National Geographic Information Institute official EMD",
        "licence": "ODbL 1.0 base; official public data free use",
        "files": [
            {
                "path": geojson_path.name,
                "bytes": geojson_path.stat().st_size,
                "sha256": sha256_file(geojson_path),
            }
        ],
        "region_count": len(collection["features"]),
        "levels": {
            level: sum(
                1
                for feature in collection["features"]
                if feature["properties"]["level"] == level
            )
            for level in ("SIDO", "SIGUNGU", "EUPMYEONDONG")
        },
        "official_emd_source": {
            "name": SOURCE_NAME,
            "url": SOURCE_URL,
            "version": SOURCE_VERSION,
            "csv_sha256": CSV_SHA256,
        },
    }
    manifest_path = output_root / "manifest.json"
    with manifest_path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    args = parser.parse_args()
    collection = build_collection(args.base, args.csv)
    print(
        json.dumps(
            write_snapshot(collection, args.output, args.snapshot_id),
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
