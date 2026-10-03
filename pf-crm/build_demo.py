#!/usr/bin/env python3
"""Build demo-site/: a static, serverless copy of the CRM that runs entirely in the browser.

It reuses the real code: server.py runs inside Pyodide (Python compiled to WebAssembly) and the
front end is the same static/ folder, so the demo can't drift from the app. Host the resulting
folder anywhere that serves static files (Netlify, GitHub Pages, any web server).

    python3 build_demo.py

The Pyodide runtime (~13 MB) is fetched once with `npm pack` (needs Node/npm) and then kept in
demo-site/pyodide/ so later rebuilds are instant and offline.
"""
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "demo-site")
PYODIDE_VERSION = "314.0.7"
PYODIDE_FILES = ["pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"]

HEADERS = """# Netlify: cache the big runtime forever (only honoured when this file is at the root of the site)
/pyodide/*
  Cache-Control: public, max-age=31536000, immutable
"""


def ensure_pyodide(dest):
    if all(os.path.exists(os.path.join(dest, f)) for f in PYODIDE_FILES):
        return
    if not shutil.which("npm"):
        sys.exit("npm is needed once to download the Pyodide runtime (install Node.js from nodejs.org), "
                 "or copy an existing demo-site/pyodide/ folder into place.")
    os.makedirs(dest, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["npm", "pack", f"pyodide@{PYODIDE_VERSION}", "--silent"], cwd=tmp, check=True,
                       shell=(os.name == "nt"))
        tgz = next(f for f in os.listdir(tmp) if f.endswith(".tgz"))
        with tarfile.open(os.path.join(tmp, tgz)) as t:
            for name in PYODIDE_FILES:
                with t.extractfile(f"package/{name}") as src, open(os.path.join(dest, name), "wb") as dst:
                    shutil.copyfileobj(src, dst)


def patch_index(html):
    def sub(old, new):
        assert old in html, f"index.html changed; couldn't find {old!r}"
        return html.replace(old, new, 1)
    html = sub("<title>", '<meta name="robots" content="noindex">\n<title>')
    html = sub('<link rel="stylesheet" href="style.css">', '<link rel="stylesheet" href="style.css">\n<link rel="stylesheet" href="demo.css">')
    html = sub("<body>", '<body>\n<div id="demo-loading"><div><b>Loading demo&hellip;</b>'
                         "<p>Starting the app in your browser. The first visit downloads a few MB; after that it opens quickly.</p></div></div>")
    html = sub("</nav>", '</nav>\n  <div id="demo-note"><b>DEMO</b><br>Fictional data. This runs entirely in your browser: '
                         'nothing you enter is saved or sent anywhere. <a href="" onclick="location.reload();return false">Reset</a>'
                         '<a href="#" id="demo-tour-link">Take the guided tour</a></div>')
    return sub('<script src="app.js"></script>',
               '<script src="demo-shim.js"></script>\n<script src="app.js"></script>\n<script src="demo-tour.js"></script>')


def main():
    os.makedirs(OUT, exist_ok=True)
    for name in os.listdir(OUT):  # rebuild everything except the downloaded runtime
        if name != "pyodide":
            p = os.path.join(OUT, name)
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    ensure_pyodide(os.path.join(OUT, "pyodide"))
    static = os.path.join(HERE, "static")
    for name in os.listdir(static):
        if name != "index.html":
            shutil.copy(os.path.join(static, name), OUT)
    with open(os.path.join(static, "index.html"), encoding="utf-8") as f:
        index = patch_index(f.read())
    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as f:
        f.write(index)
    for name in ("demo-shim.js", "demo-tour.js", "demo.css"):
        shutil.copy(os.path.join(HERE, "demo", name), OUT)
    os.makedirs(os.path.join(OUT, "app"), exist_ok=True)
    shutil.copy(os.path.join(HERE, "server.py"), os.path.join(OUT, "app", "server.py"))
    with open(os.path.join(OUT, "_headers"), "w") as f:
        f.write(HEADERS)
    size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(OUT) for f in fs) / 1e6
    print(f"Built {OUT} ({size:.1f} MB). Drag that folder onto Netlify (app.netlify.com/drop) or copy it into your site.")


if __name__ == "__main__":
    main()
