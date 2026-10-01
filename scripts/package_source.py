"""Create a source-only archive without user databases, credentials or build caches."""
from pathlib import Path
import os
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'.venv', 'node_modules', '.npm-cache', '.cache', '__pycache__',
            '.pytest_cache', 'build', 'release', 'dist', 'data', '.git'}


def main():
    output = ROOT.parent / 'campus-agent-source.zip'
    count = 0
    with ZipFile(output, 'w', compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for directory, folders, files in os.walk(ROOT):
            folders[:] = sorted(name for name in folders if name not in EXCLUDED)
            for name in sorted(files):
                file = Path(directory) / name
                relative = file.relative_to(ROOT)
                if file.name == '.env' or file.name.startswith('.env.') and file.name != '.env.example':
                    continue
                if file.suffix.lower() in {'.db', '.sqlite', '.sqlite3', '.log', '.pyc'}:
                    continue
                archive.write(file, Path('campus-agent') / relative)
                count += 1
    with ZipFile(output) as archive:
        assert archive.testzip() is None
        assert not any(Path(name).name == '.env' for name in archive.namelist())
    print(f'Source archive verified: {output} ({count} files, {output.stat().st_size} bytes)')


if __name__ == '__main__':
    main()
