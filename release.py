#!/usr/bin/env python3
"""One-command release.

  python3 release.py 55.12 "What changed"                   bump, test and build a dotted release
  python3 release.py V2026-11-24-01 "What changed" --publish also publish a date-based release

The new version is written to every file that carries it, the changelog and manifest get a new entry,
verify.py and the tests run, and the zip is built. Nothing is committed unless --publish is given.
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION_PATTERN = r'(?:\d+\.\d+|\d{4}-\d{2}-\d{2}-\d{2})'
VERSIONED = ['ARCHITECTURE.md', 'README.md', 'DEPLOYMENT.md', 'MAPPING.md', 'version.py', 'core.py', 'manifest.json',
             'weathercam_dashboard/dashboard.py', 'weathercam_dashboard/templates/dashboard.html']
TRAILER = 'Co-authored-by: copilot-swe-agent[bot] <198982749+Copilot@users.noreply.github.com>'


def run(*cmd, check=True):
    print('$', ' '.join(cmd))
    return subprocess.run(cmd, cwd=ROOT, check=check)


def current_version():
    return re.search(r'VERSION="V(' + VERSION_PATTERN + r')"', (ROOT / 'version.py').read_text(encoding='utf-8')).group(1)


def bump(old, new, today):
    pattern = re.compile(r'(?<![\d.])' + re.escape(old) + r'(?!\.?\d)')
    for name in VERSIONED:
        path = ROOT / name
        text = pattern.sub(new, path.read_text(encoding='utf-8'))
        if name == 'version.py':
            text = re.sub(r'VERSION_DATE="[\d-]+"', 'VERSION_DATE="%s"' % today, text)
        elif name == 'core.py':
            text = re.sub(r"(SCRIPT_VERSION = ')[\d-]+( V)", r'\g<1>%s\2' % today, text)
        elif name == 'manifest.json':
            text = re.sub(r'("built": ")[\d-]+', r'\g<1>' + today, text)
            text = text.replace('"features": [\n', '"features": [\n    %s,\n' % json.dumps(CHANGE), 1)
        path.write_text(text, encoding='utf-8')
    log = ROOT / 'CHANGELOG.md'
    log.write_text('#### V%s\n- %s\n\n' % (new, CHANGE) + log.read_text(encoding='utf-8'), encoding='utf-8')


def main():
    global CHANGE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('version', help='new version, e.g. 55.14 or V2026-11-24-01')
    ap.add_argument('change', help='one-line description for the changelog')
    ap.add_argument('--publish', action='store_true', help='commit, push main and create the GitHub release')
    args = ap.parse_args()
    CHANGE = args.change.strip()
    new, old = args.version.lstrip('Vv'), current_version()
    if not re.fullmatch(VERSION_PATTERN, new):
        sys.exit('Version must be dotted (55.14) or date-based (2026-11-24-01)')
    if new != old:
        bump(old, new, date.today().isoformat())
    run(sys.executable, 'verify.py')
    run(sys.executable, '-m', 'unittest', 'test_site_smoke')
    if subprocess.run([sys.executable, '-m', 'pytest', '--version'], cwd=ROOT, capture_output=True).returncode == 0:
        run(sys.executable, '-m', 'pytest', '-q', 'test_v54_9.py', 'test_weather_station.py')
    else:
        print('pytest not installed: skipped test_v54_9.py and test_weather_station.py (pip install pytest)')
    run(sys.executable, 'build_release.py')
    zipfile = 'dist/HWS-Webcam-Control-%s.zip' % new
    if not args.publish:
        print('Built %s. Re-run with --publish to commit, push and release.' % zipfile)
        return
    run('git', 'add', '-A')
    run('git', 'commit', '-m', 'Release V%s: %s\n\n%s' % (new, CHANGE, TRAILER))
    run('git', 'push', 'origin', 'HEAD:main')
    run('gh', 'release', 'create', 'V' + new, zipfile, '--target', 'main', '--title', 'V' + new, '--notes', CHANGE, '--latest')


if __name__ == '__main__':
    main()
