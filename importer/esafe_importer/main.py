from __future__ import annotations

import json
import sys

from esafe_importer.config import ImportConfig
from esafe_importer.database import ReferenceDatabaseImporter


def main() -> None:
    try:
        config = ImportConfig.from_environment()
        result = ReferenceDatabaseImporter(config).run()
    except Exception as error:
        print(
            json.dumps(
                {"status": "FAILED", "error_type": type(error).__name__, "message": str(error)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
            flush=True,
        )
        raise
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")), flush=True)
