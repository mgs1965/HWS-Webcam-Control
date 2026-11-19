#!/usr/bin/env python3
"""Build the release zip from manifest.json.

The archive is named HWS-Webcam-Control-<version>.zip and every entry lives under
HWS-Webcam-Control-<version>/, so extracting it creates a matching directory.
Usage: python3 build_release.py [output_directory]   (default: ./dist)
"""
import json
import sys
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parent
manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
package = manifest['package']
directory = manifest['package_directory']
version = manifest['release'][1:]
if package != f'HWS-Webcam-Control-{version}.zip' or directory != f'HWS-Webcam-Control-{version}':
    raise SystemExit(f'Manifest package naming is inconsistent: {package} / {directory}')

def release_files():
    for name in manifest['files']:
        path = root / name
        if path.is_dir():
            yield from sorted(p for p in path.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
        else:
            yield path

output_directory = Path(sys.argv[1] if len(sys.argv) > 1 else root / 'dist')
output_directory.mkdir(parents=True, exist_ok=True)
target = output_directory / package
with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
    for path in release_files():
        archive.write(path, f'{directory}/{path.relative_to(root).as_posix()}')
print(f'Built {target} ({target.stat().st_size / 1024:.0f} KB) -> extracts to {directory}/')
