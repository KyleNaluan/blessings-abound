"""Write the API's OpenAPI schema to a file, for generating the web client without a running server.

Usage: uv run python -m app.export_openapi <output.json>
"""

import json
import sys
from pathlib import Path

from app.main import app

if __name__ == "__main__":
    output = Path(sys.argv[1])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8", newline="\n")
