"""Keep the pip installation lock derived from uv.lock, including the dev extra."""

import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADER = """# Generated from uv.lock; do not edit or regenerate with pip freeze.
# Refresh: python scripts/export-requirements.py
# Verify: python scripts/export-requirements.py --check
# Install: uv pip install -r requirements.lock
#          uv pip install --no-deps -e .
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = subprocess.run(
        ["uv", "export", "--locked", "--offline", "--extra", "dev",
         "--no-emit-project", "--no-header", "--no-annotate"],
        cwd=ROOT, text=True, stdout=subprocess.PIPE, check=True,
    )
    expected = HEADER + result.stdout
    target = ROOT / "requirements.lock"
    if args.check:
        if not target.exists() or target.read_text(encoding="utf-8") != expected:
            print("requirements.lock differs from uv.lock; run scripts/export-requirements.py")
            return 1
    else:
        target.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
