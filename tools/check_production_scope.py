"""Reject retired service-scope wording in maintained instructions and MCP texts."""

from pathlib import Path
import re
import sys


RETIRED_SCOPE = re.compile(r"\bhackathon\b|\b(?:for the|full|complete) metric\b|\bM1 prototype\b", re.IGNORECASE)
PATTERNS = (
    "README.md", "AGENTS.md", "app/**/AGENTS.md", "skills/**/*.md", "drawing2cad-mcp/README.md",
    "drawing2cad-mcp/src/**/*.py", "app/backend/src/**/*.py", "app/frontend/src/**/*.ts",
    "app/frontend/src/**/*.tsx", "app/backend/README.md", "app/frontend/README.md",
)


def findings(root: Path) -> list[str]:
    paths = sorted({path for pattern in PATTERNS for path in root.glob(pattern) if path.is_file()})
    return [f"{path.relative_to(root).as_posix()}:{number}: {line.strip()}"
            for path in paths for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if RETIRED_SCOPE.search(line)]


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    violations = findings(root)
    if violations:
        print("\n".join(violations))
        print("Describe the current delivery scope in maintained service texts.", file=sys.stderr)
        return 1
    print("Maintained service texts use the current delivery scope.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
