"""Build a public archive, or an explicit private backup with game data."""
from __future__ import annotations
import argparse
import sqlite3
import zipfile
from pathlib import Path

FILES = [
    '.gitignore', '.gitattributes', '.editorconfig',
    '.github/workflows/ci.yml', '.github/ISSUE_TEMPLATE/bug_report.yml',
    '.github/ISSUE_TEMPLATE/feature_request.yml', '.github/ISSUE_TEMPLATE/config.yml',
    '.github/PULL_REQUEST_TEMPLATE.md',
    'Start.cmd', 'Setup.cmd', 'README.md', 'LICENSE', 'SECURITY.md', 'THIRD_PARTY_NOTICES.md',
    'docs/FAQ.md', 'docs/COMPATIBILITY.md', 'docs/assets/banner.svg',
    'CONTRIBUTING.md', 'CHANGELOG.md', 'WuwaRu.spec', 'requirements-dev.txt',
    'make_portable.py', 'config.example.json', 'glossary.json', 'overrides.json',
    'terms.json', 'choices.json', 'main.py', 'game.py', 'translator.py',
    'wuwa_pak.py', 'test_translation.py', 'verify_package.py',
    'audit_and_repair.py', 'tools/README.md', 'tools/Setup-tools.ps1',
    'tools/fmodel/LICENSE', 'tools/fmodel/NOTICE',
    'tools/fmodel/LICENSE_COMPLIANCE.md',
]


def make_archive(home: Path, destination: Path, include_data=False, executable=None):
    files = [(home / name, name) for name in FILES]
    for path, _ in files:
        if not path.is_file():
            raise FileNotFoundError(path)
    if executable:
        if not executable.is_file():
            raise FileNotFoundError(executable)
        files.append((executable, 'WuwaRu.exe'))
    if include_data:
        cache = home / 'data/cache.sqlite3'
        if cache.exists():
            with sqlite3.connect(cache) as db:
                db.execute('pragma wal_checkpoint(TRUNCATE)')
        # Explicit paths only: data/pak-input contains junctions into the game.
        for name in ('config.json', 'tools/fmodel/FModelCLI.exe', 'tools/pakkeys.txt',
                     'output', 'data/source', 'data/source-manifest.json',
                     'data/cache.sqlite3'):
            path = home / name
            if path.is_dir():
                files.extend((item, item.relative_to(home).as_posix())
                             for item in path.rglob('*') if item.is_file())
            elif path.is_file():
                files.append((path, name))
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + '.tmp')
    try:
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path, name in files:
                archive.write(path, 'WuwaRu/' + name)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def main():
    home = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--include-data', action='store_true',
                        help='Private backup: include cache, game DBs and compiled PAK')
    parser.add_argument('--exe', type=Path, help='Optional compiled WuwaRu.exe')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    filename = 'WuwaRu-local-backup.zip' if args.include_data else 'WuwaRu-source.zip'
    output = args.output or home / 'dist' / filename
    print(make_archive(home, output, args.include_data, args.exe))


if __name__ == '__main__':
    main()
