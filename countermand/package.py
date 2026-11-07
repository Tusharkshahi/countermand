"""Create a source-only handoff archive, never including local state or credentials."""

import argparse
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
TOP = {".gitignore", "README.md", "WINDOWS.md", "pyproject.toml",
       "start-windows.cmd", "check-windows.cmd", "configure-github.cmd"}
FOLDERS = {"countermand", "web", "switch", "tests", "docs"}
SUFFIXES = {".py", ".md", ".html", ".css", ".js", ".mjs", ".svg", ".png"}


def source_files():
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part.startswith(".") or part == "__pycache__" for part in relative.parts[:-1]):
            continue
        if (len(relative.parts) == 1 and path.name in TOP
                or relative.parts[0] in FOLDERS and path.suffix in SUFFIXES):
            yield path, relative


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "countermand-windows-source.zip")
    args = parser.parse_args()
    with zipfile.ZipFile(args.output, "x", zipfile.ZIP_DEFLATED) as archive:
        for path, relative in source_files():
            archive.write(path, Path("countermand") / relative)
    print(f"Source-only archive: {args.output}")
    print("Excluded: .git, .countermand, generated credentials, databases, logs, and browser profiles.")


if __name__ == "__main__":
    main()
