#!/usr/bin/env python3
"""Generate OpenAPI specification from FastAPI app code.

Imports the FastAPI app, calls app.openapi() to produce the spec,
and writes it to stdout or a file. No running server needed.

Requires Python 3.12+ (matching project minimum).
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Disable OpenTelemetry exports to avoid collector connection attempts
os.environ["OTEL_TRACES_EXPORTER"] = "none"
os.environ["OTEL_METRICS_EXPORTER"] = "none"

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app import create_app  # noqa: E402
from app.config import Config  # noqa: E402


def generate_spec() -> dict:  # type: ignore[type-arg]
    """Generate OpenAPI spec from FastAPI app."""
    config = Config()
    app = create_app(config)
    return dict(app.openapi())


def main() -> None:
    parser = argparse.ArgumentParser(description="Export OpenAPI spec from FastAPI app")
    parser.add_argument(
        "-o",
        "--output",
        help="Output file path (default: stdout)",
    )
    args = parser.parse_args()

    spec = generate_spec()

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(spec, indent=2) + "\n")
        print(f"OpenAPI spec written to {output_path}", file=sys.stderr)
    else:
        print(json.dumps(spec, indent=2))


if __name__ == "__main__":
    main()
