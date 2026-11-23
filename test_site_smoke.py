#!/usr/bin/env python3
"""Generate the site with no data and load every page in headless Chrome, failing on any JavaScript error.
Skips when Chrome is not installed. Run with: python3 -m unittest test_site_smoke -v"""
import os, re, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHROME = next((c for c in (os.environ.get('CHROME_BIN'), '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
               shutil.which('google-chrome'), shutil.which('chromium'), shutil.which('chromium-browser')) if c and Path(c).exists()), None)
HOOK = '<script>window.__errs=[];addEventListener("error",e=>__errs.push(e.message));addEventListener("unhandledrejection",e=>__errs.push(String(e.reason)));' \
       'addEventListener("load",()=>setTimeout(()=>{const d=document.createElement("pre");d.id="hws-errs";d.textContent=JSON.stringify(__errs);document.body.append(d)},300))</script>'


class SiteSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='hws-smoke-'))
        env = dict(os.environ, WEATHERCAM_ROOT=str(cls.tmp / 'root'), DASHBOARD_OUT=str(cls.tmp / 'out'))
        (cls.tmp / 'root').mkdir()
        subprocess.run([sys.executable, str(HERE / 'weathercam_dashboard' / 'dashboard.py')], env=env, check=True, capture_output=True)
        cls.out = cls.tmp / 'out'

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_all_pages_share_navigation_and_width(self):
        css = (self.out / 'site.css').read_text()
        self.assertIn('--page-w:1550px', css)
        for page in self.out.glob('*.html'):
            if page.name in ('mobile.html', 'index.html') or 'weather34' in page.name:
                continue
            self.assertIn('site.js', page.read_text(), page.name)

    @unittest.skipUnless(CHROME, 'Chrome not installed')
    def test_no_javascript_errors(self):
        for page in sorted(self.out.glob('*.html')):
            html = page.read_text()
            if 'site.js' not in html:
                continue
            probe = self.out / ('probe-' + page.name)
            probe.write_text(re.sub(r'<head>', '<head>' + HOOK, html, count=1))
            res = subprocess.run([CHROME, '--headless=new', '--disable-gpu', '--no-sandbox', '--virtual-time-budget=4000',
                                  '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost',
                                  '--dump-dom', probe.as_uri()], capture_output=True, text=True, timeout=60)
            m = re.search(r'<pre id="hws-errs">(.*?)</pre>', res.stdout, re.S)
            self.assertIsNotNone(m, page.name + ' did not finish loading')
            self.assertEqual(m.group(1).strip(), '[]', page.name + ' raised JavaScript errors')


if __name__ == '__main__':
    unittest.main()
