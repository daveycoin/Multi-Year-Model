/* Demo mode: runs the real server code (server.py) inside the browser with Pyodide (Python compiled to WebAssembly),
   and answers the app's /api calls locally. No backend, no network calls, nothing leaves the visitor's computer.
   Loaded before app.js; app.js itself is unchanged. */
(() => {
  "use strict";
  const realFetch = window.fetch.bind(window);
  const base = new URL(".", document.currentScript.src).href;  // the folder this site lives in (works in a sub-folder too)
  const pad = n => String(n).padStart(2, "0");
  const localISO = () => { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };

  const ready = (async () => {
    try {
      const { loadPyodide } = await import(base + "pyodide/pyodide.mjs");
      const py = await loadPyodide({ indexURL: base + "pyodide/" });
      const src = await (await realFetch(base + "app/server.py")).text();
      py.FS.mkdirTree("/app");
      py.FS.writeFile("/app/server.py", src);
      py.runPython(`
import os, sys, json, base64, datetime
os.environ["PFCRM_DB"] = "/tmp/crm.db"
sys.path.insert(0, "/app")
import server
_c = server.connect(); server.seed_demo(_c); _c.close()

def demo_call(method, path, body, today):
    code, payload, ctype, headers = server.handle_api(method, path, body, datetime.date.fromisoformat(today))
    b64 = None
    if isinstance(payload, (dict, list)):
        payload = json.dumps(payload)
    elif isinstance(payload, bytes):
        b64, payload = base64.b64encode(payload).decode(), ""
    return {"code": code, "ctype": ctype, "text": payload, "b64": b64, "headers": headers}
`);
      document.getElementById("demo-loading")?.remove();
      return py.globals.get("demo_call");
    } catch (err) {
      const box = document.getElementById("demo-loading");
      if (box) box.innerHTML = `<div><b>Sorry, the demo couldn't start.</b><p>${String(err.message || err)}</p>
        <p>It needs a current desktop browser (Chrome, Edge, Firefox or Safari) with WebAssembly enabled.</p></div>`;
      throw err;
    }
  })();

  window.fetch = async (input, init = {}) => {
    const u = new URL(typeof input === "string" ? input : input.url, location.href);
    if (!u.pathname.includes("/api/")) return realFetch(input, init);
    const call = await ready;
    const proxy = call((init.method || "GET").toUpperCase(), u.pathname + u.search, typeof init.body === "string" ? init.body : "", localISO());
    const r = proxy.toJs({ dict_converter: Object.fromEntries });
    proxy.destroy();
    const body = r.b64 ? Uint8Array.from(atob(r.b64), c => c.charCodeAt(0)) : r.text;
    return new Response(body, { status: r.code, headers: { "Content-Type": r.ctype, ...(r.headers || {}) } });
  };

  // Plain links to /api/... (digest preview, backup download) can't be intercepted by fetch, so do them here.
  document.addEventListener("click", async e => {
    const a = e.target.closest('a[href^="/api/"]');
    if (!a) return;
    e.preventDefault();
    const win = a.target === "_blank" ? window.open("", "_blank") : null;
    const res = await window.fetch(a.getAttribute("href"));
    const url = URL.createObjectURL(await res.blob());
    if (win) { win.location = url; return; }
    const dl = document.createElement("a");
    dl.href = url;
    dl.download = (/filename=(.+)$/.exec(res.headers.get("Content-Disposition") || "") || [])[1] || "download";
    dl.click();
  });
})();
