"""Build the release zip for HACS.

The zip holds only the files Home Assistant loads: the Python modules, the
JSON/YAML metadata, the translations and the built frontend. Tests, sources,
firmware, scripts and design documents stay out.
"""

import argparse
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent.parent
EXCLUDED_DIRS = {
    "tests",
    "frontend-src",
    "node_modules",
    "esphome",
    "scripts",
    "design",
    ".github",
    ".git",
    "dist",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}
INCLUDED_ROOT_FILES = {
    "manifest.json",
    "strings.json",
    "icons.json",
    "services.yaml",
    "py.typed",
}


def _included(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if any(part in EXCLUDED_DIRS or part.startswith(".") for part in relative.parts):
        return False
    if len(relative.parts) == 1:
        return path.suffix == ".py" or relative.name in INCLUDED_ROOT_FILES
    top = relative.parts[0]
    if top == "frontend":
        return True
    return path.suffix in {".py", ".json"}


def build(output: Path) -> list[str]:
    """Write the zip and return the archived names."""
    names: list[str] = []
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file() and _included(path):
                name = path.relative_to(ROOT).as_posix()
                archive.write(path, name)
                names.append(name)
    return names


def main() -> None:
    """Parse arguments and build the zip."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "dist" / "daikin_heat_pump_control.zip"
    )
    args = parser.parse_args()
    for name in build(args.output):
        print(name)


if __name__ == "__main__":
    main()
