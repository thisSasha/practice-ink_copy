import os, re, sys, json, time, pathlib, logging
from urllib.parse import urljoin, urlparse, urldefrag
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

BASE = "https://practice.inc"
BASE_HTML = BASE + "/"
ROOT_HTML = "index.html"
UA = "fetcher/4.4"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept": "*/*"})
ABS_HOST = urlparse(BASE).netloc

LOG_PATH = "crawl.log"
REPORT_PATH = "rewrite-report.json"

DENY_PREFIXES = []
ACCEPT_EXT = {
    ".html",".htm",".css",".js",".mjs",".json",".map",".xml",".svg",".txt",".csv",".webmanifest",
    ".png",".jpg",".jpeg",".webp",".gif",".avif",".ico",
    ".mp4",".webm",".ogg",".mp3",".wav",
    ".woff",".woff2",".ttf",".otf",".eot",".wasm"
}
TEXT_HINT = ("text/","javascript","json","xml","svg","webmanifest","csv","module")
BINARY_HINT = ("image/","font/","audio/","video/","application/wasm")

HTML_ATTR_RES = [
    (re.compile(r'<link\b[^>]*?\bhref=["\']([^"\']+)["\']', re.I|re.S), 1),
    (re.compile(r'<script\b[^>]*?\bsrc=["\']([^"\']+)["\']', re.I|re.S), 1),
    (re.compile(r'<img\b[^>]*?\bsrc=["\']([^"\']*)["\']', re.I|re.S), 1),
    (re.compile(r'<img\b[^>]*?\bsrcset=["\']([^"\']+)["\']', re.I|re.S), 1),
    (re.compile(r'<img\b[^>]*?\bdata-src=["\']([^"\']+)["\']', re.I|re.S), 1),
    (re.compile(r'<img\b[^>]*?\bdata-srcset=["\']([^"\']+)["\']', re.I|re.S), 1),
    (re.compile(r'<source\b[^>]*?\bsrc=["\']([^"\']+)["\']', re.I|re.S), 1),
    (re.compile(r'<source\b[^>]*?\bsrcset=["\']([^"\']+)["\']', re.I|re.S), 1),
    (re.compile(r'<video\b[^>]*?\bposter=["\']([^"\']+)["\']', re.I|re.S), 1),
    (re.compile(r'<a\b[^>]*?\bhref=["\']([^"\']+)["\']', re.I|re.S), 1),
    (re.compile(r'\bdata-href=["\']([^"\']+)["\']', re.I|re.S), 1),
    (re.compile(r'<image\b[^>]*?\b(?:href|xlink:href)=["\']([^"\']+)["\']', re.I|re.S), 1),
    (re.compile(r'<use\b[^>]*?\b(?:href|xlink:href)=["\']([^"\']+)["\']', re.I|re.S), 1),
]

CSS_URL_RE = re.compile(r'@import\s+["\']([^"\']+)["\']|url\(\s*["\']?([^\s<>"\')]+)["\']?\s*\)', re.I)
JS_PATTERNS = [
    re.compile(r'\bimport\s*[(]\s*["\']([^"\']+)["\']\s*[)]', re.I),
    re.compile(r'\bexport\s+[^;]*?\bfrom\s+["\']([^"\']+)["\']', re.I),
    re.compile(r'\bimport\s+[^"\']*?\bfrom\s+["\']([^"\']+)["\']', re.I),
    re.compile(r'\brequire\s*[(]\s*["\']([^"\']+)["\']\s*[)]', re.I),
    re.compile(r'\bnew\s+Worker\s*[(]\s*["\']([^"\']+)["\']', re.I),
    re.compile(r'\bnavigator\.serviceWorker\.register\s*[(]\s*["\']([^"\']+)["\']', re.I),
    re.compile(r'\bimportScripts\s*[(]\s*["\']([^"\']+)["\']', re.I),
    re.compile(r'\bnew\s+URL\s*[(]\s*["\']([^"\']+)["\']\s*,\s*import\.meta\.url\s*[)]', re.I),
]
GEN_STR_URL_RE = re.compile(r'(?<![<\w-])["\'](\/[A-Za-z0-9._~/%\-+?=&:@;,!$*()#]+)["\']')

DOMAIN_RE = re.compile(r'https?://practice\.inc(?=[/\'")\s]|$)', re.I)

REWRITE_REPORT = {"html": [], "css": [], "js": []}

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler(sys.stdout)]
    )
    logging.info("=== crawl start ===")
    logging.info(f"BASE={BASE}  UA={UA}")

def log_rewrite(kind, src_file, orig, new):
    REWRITE_REPORT[kind].append({"file": src_file, "from": orig, "to": new})
    if new.startswith(".") or new.startswith("../"):
        target = os.path.normpath(os.path.join(os.path.dirname(src_file) or ".", new))
        if not os.path.exists(target):
            logging.warning(f"[MISS] {kind} ref points to missing local file: {new} (from {orig}) in {src_file}")

def is_same_origin(u):
    p = urlparse(u)
    if not p.scheme and not p.netloc:
        return True
    return p.scheme in ("http","https") and p.netloc == ABS_HOST

def absolutize(u, base_url):
    u = (u or "").strip()
    if not u or u.startswith(("data:","blob:")):
        return None
    if u.startswith("//"):
        u = "https:" + u
    if u.startswith("http://") or u.startswith("https://"):
        return u if urlparse(u).netloc == ABS_HOST else None
    return urljoin(base_url, u)

def is_dir_like(u):
    path = urlparse(u).path
    return path.endswith("/") or path == ""

def want_any(u):
    path = urlparse(u).path
    if any(path.startswith(x) for x in DENY_PREFIXES):
        return False
    if is_dir_like(u):
        return True
    suf = pathlib.Path(path).suffix.lower()
    return suf in ACCEPT_EXT or suf == ""

def want_extension_css(u):
    path = urlparse(u).path
    if any(path.startswith(x) for x in DENY_PREFIXES):
        return False
    if is_dir_like(u):
        return False
    suf = pathlib.Path(path).suffix.lower()
    return suf in ACCEPT_EXT

def want_extension_js(u):
    path = urlparse(u).path
    if any(path.startswith(x) for x in DENY_PREFIXES):
        return False
    if is_dir_like(u):
        return False
    suf = pathlib.Path(path).suffix.lower()
    return suf in ACCEPT_EXT or suf == ""

def want_extension_jsonlike(u):
    path = urlparse(u).path
    if any(path.startswith(x) for x in DENY_PREFIXES):
        return False
    if is_dir_like(u):
        return False
    suf = pathlib.Path(path).suffix.lower()
    return suf in {".json",".webmanifest",".xml",".map",".svg",".txt",".csv"}

def local_path_for(u):
    u, _ = urldefrag(u)
    p = urlparse(u)
    path = p.path or "/"
    if path.endswith("/"):
        path += "index.html"
    local = "." + path
    if not os.path.splitext(local)[1]:
        local += ".html"
    if p.query:
        safe_q = re.sub(r'[^A-Za-z0-9._-]+', "_", p.query)
        base, ext = os.path.splitext(local)
        local = f"{base}__q_{safe_q}{ext or ''}"
    return os.path.normpath(local)

def ensure_parent(path):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)

def is_text_content(ct, head_bytes):
    if ct:
        c = ct.lower()
        if any(x in c for x in TEXT_HINT):
            return True
        if any(x in c for x in BINARY_HINT):
            return False
    try:
        head_bytes.decode("utf-8")
        return True
    except:
        return False

def strip_data_vue_tag_aggressive(text):
    return text

def to_local_rel(url_value, local_path, kind):
    u = url_value.strip()
    u_clean = DOMAIN_RE.sub("", u)
    p = urlparse(u_clean)
    if not p.path.startswith("/"):
        return url_value
    target = "." + p.path
    if target.endswith("/"):
        target += "index.html"
    if not os.path.splitext(target)[1]:
        target += ".html"
    if p.query:
        safe_q = re.sub(r'[^A-Za-z0-9._-]+', "_", p.query)
        base, ext = os.path.splitext(target)
        target = f"{base}__q_{safe_q}{ext or ''}"
    rel = os.path.relpath(os.path.normpath(target), os.path.dirname(local_path) or ".").replace(os.sep, "/")
    if p.fragment:
        rel += f"#{p.fragment}"
    log_rewrite(kind, local_path, url_value, rel)
    return rel

def rewrite_importmap_urls(html, local_path):
    rx = re.compile(r'<script\b[^>]*\btype=["\']importmap["\'][^>]*>(.*?)</script>', re.I|re.S)
    def repl(m):
        try:
            raw = m.group(1)
            data = json.loads(DOMAIN_RE.sub("", raw))
            imps = data.get("imports") or {}
            for k,v in list(imps.items()):
                if isinstance(v, str) and (v.startswith("/") or DOMAIN_RE.search(v)):
                    imps[k] = to_local_rel(v, local_path, "js")
            new = json.dumps(data, ensure_ascii=False)
            return m.group(0).replace(raw, new)
        except Exception as e:
            logging.error(f"[IMPORTMAP] parse error in {local_path}: {e}")
            return m.group(0)
    return rx.sub(repl, html)

def rewrite_html_urls(html, local_path):
    t = DOMAIN_RE.sub("/", html)
    t = re.sub(r'<base\b[^>]*>', '', t, flags=re.I)
    for rx, grp in HTML_ATTR_RES:
        def rfunc(m):
            val = m.group(grp)
            if val is None:
                return m.group(0)
            if "srcset" in rx.pattern:
                parts = []
                for chunk in (val or "").split(","):
                    chunk = chunk.strip()
                    if not chunk:
                        continue
                    bits = chunk.split()
                    u = bits[0]
                    if u.startswith("/") or DOMAIN_RE.search(u):
                        bits[0] = to_local_rel(u, local_path, "html")
                    parts.append(" ".join(bits))
                newval = ", ".join(parts)
                return m.group(0).replace(val, newval)
            else:
                u = (val or "").strip()
                if u.startswith("/") or DOMAIN_RE.search(u):
                    newval = to_local_rel(u, local_path, "html")
                    return m.group(0).replace(val, newval)
                return m.group(0)
        t = rx.sub(rfunc, t)
    t = rewrite_importmap_urls(t, local_path)
    mark = '<script>window.__LOCAL_ARCHIVE__=true;</script>'
    if "</head>" in t:
        t = t.replace("</head>", mark + "</head>")
    else:
        t = mark + t
    return t

def rewrite_css_urls(text, local_path):
    def rfunc(m):
        u = m.group(1) or m.group(2)
        if not u:
            return m.group(0)
        nu = DOMAIN_RE.sub("", u)
        if nu.startswith("/"):
            nu = to_local_rel(nu, local_path, "css")
        if m.group(1):
            return m.group(0).replace(m.group(1), nu)
        return m.group(0).replace(m.group(2), nu)
    return CSS_URL_RE.sub(rfunc, text)

def rewrite_js_urls(text, local_path):
    t = DOMAIN_RE.sub("/", text)
    for rx in JS_PATTERNS:
        def rfunc(m):
            u = m.group(1)
            nu = u
            if nu.startswith("/") or DOMAIN_RE.search(nu):
                nu = to_local_rel(nu, local_path, "js")
            return m.group(0).replace(u, nu)
        t = rx.sub(rfunc, t)
    return t

def sniff_kind_by_ct(ct):
    c = (ct or "").lower()
    if "text/html" in c: return "html"
    if "text/css" in c: return "css"
    if "javascript" in c or "ecmascript" in c or "module" in c: return "js"
    if "image/svg+xml" in c: return "html"
    if "json" in c or "xml" in c or "svg" in c or "csv" in c or "webmanifest" in c or "/map" in c: return "jsonlike"
    return "other"

def sniff_kind_by_url(url):
    path = urlparse(url).path.lower()
    if path.endswith((".css",)): return "css"
    if path.endswith((".mjs",".js")): return "js"
    if path.endswith((".json",".webmanifest",".xml",".svg",".txt",".csv",".map")): return "jsonlike"
    if path.endswith((".html",".htm")) or path.endswith("/"): return "html"
    return "other"

def parse_and_enqueue(url, text, queue, content_type=None):
    kind = sniff_kind_by_ct(content_type) if content_type else sniff_kind_by_url(url)
    if kind == "css":
        queue.update(extract_from_css(text, url))
    elif kind == "js":
        queue.update(extract_from_js(text, url))
    elif kind == "jsonlike":
        queue.update(extract_from_json_like(text, url))
    elif kind == "html":
        queue.update(extract_from_html(text, url))

def save_text_html(path, html):
    ensure_parent(path)
    html = strip_data_vue_tag_aggressive(html)
    html = rewrite_html_urls(html, path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    logging.info(f"[WRITE] HTML {path} ({len(html)} bytes)")

def save_text_generic(path, text, kind):
    ensure_parent(path)
    text = strip_data_vue_tag_aggressive(text)
    if kind == "css":
        text = rewrite_css_urls(text, path)
    elif kind == "js":
        text = rewrite_js_urls(text, path)
    elif kind == "jsonlike":
        text = DOMAIN_RE.sub("/", text)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    logging.info(f"[WRITE] {kind.upper()} {path} ({len(text)} bytes)")

def save_bytes(path, raw, kind="bin"):
    ensure_parent(path)
    with open(path, "wb") as f:
        f.write(raw)
    logging.info(f"[WRITE] {kind.upper()} {path} ({len(raw)} bytes)")

def fetch(url):
    try:
        r = SESSION.get(url, timeout=30)
        r.raise_for_status()
        logging.info(f"[HTTP] {r.status_code} {url}")
        return r
    except Exception as e:
        logging.error(f"[HTTP-ERR] {url} :: {e}")
        raise

def try_js_fallbacks(url):
    trials = [url + ".js", url + ".mjs", url + "/index.js", url + "/index.mjs"]
    for t in trials:
        try:
            r = fetch(t)
            logging.info(f"[JS-FALLBACK] {url} → {t}")
            return t, r
        except:
            continue
    logging.warning(f"[JS-FALLBACK-FAIL] {url}")
    return None, None

def init_driver():
    o = Options()
    o.add_argument("--headless=new")
    o.add_argument("--no-sandbox")
    o.add_argument("--disable-gpu")
    o.add_argument("--window-size=1920,1080")
    o.add_argument(f"user-agent={UA}")
    d = webdriver.Chrome(options=o)
    d.set_page_load_timeout(120)
    d.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            (function(){
              if (window.__netHooked__) return; window.__netHooked__=true;
              window.__activeXHR__=0; window.__activeFetch__=0;
              const open = XMLHttpRequest.prototype.open;
              const send = XMLHttpRequest.prototype.send;
              XMLHttpRequest.prototype.open = function(){ this.addEventListener('loadend', ()=>{ window.__activeXHR__=(window.__activeXHR__||1)-1;}); return open.apply(this, arguments); };
              XMLHttpRequest.prototype.send = function(){ window.__activeXHR__=(window.__activeXHR__||0)+1; return send.apply(this, arguments); };
              const _fetch = window.fetch;
              window.fetch = function(){ window.__activeFetch__=(window.__activeFetch__||0)+1; return _fetch.apply(this, arguments).finally(()=>{ window.__activeFetch__=(window.__activeFetch__||1)-1; }); };

              const abs=(u)=>{try{ if(!u) return null; if(u.startsWith('data:')||u.startsWith('blob:')) return null;
                  if(u.startsWith('//')) return location.protocol+u; if(/^https?:\\/\\//.test(u)) return u; return new URL(u, location.href).href;}catch(e){return null}};
              const isPlace=(u)=>!u||/^https?:\\/\\/?:0$/.test(u)||/^\\/\\/:0$/.test(u)||u==='//:0'||u==='https://:0'||u==='http://:0';

              window.__imgSeen__=new WeakMap();

              const remember = (el, val, kind) => {
                const a = abs(val);
                if (!a || isPlace(a)) return;
                let rec = window.__imgSeen__.get(el);
                if (!rec) { rec = {src:null, srcset:[], best:null}; window.__imgSeen__.set(el, rec); }
                if (kind==='src') rec.src = a;
                if (kind==='srcset' && a) rec.srcset.push(a);
                const pick = rec.src || (rec.srcset[0]||null);
                if (pick && !isPlace(pick)) rec.best = pick;
              };

              const pickFromSrcset = (ss) => {
                if (!ss) return null;
                const parts = ss.split(',').map(s=>s.trim()).filter(Boolean).map(s=>{
                  const m = s.split(/\\s+/); const url = m[0];
                  const w = (m[1]||'').endsWith('w') ? parseInt(m[1]) : ((m[1]||'').endsWith('x') ? parseFloat(m[1]) : 0);
                  return {url, w: isNaN(w)?0:w};
                });
                parts.sort((a,b)=>b.w-a.w);
                return parts.length? parts[0].url : null;
              };

              const patchAttr = (proto, tagSet) => {
                const orig = proto.setAttribute;
                proto.setAttribute = function(name, value){
                  const tag = (this.tagName||'').toUpperCase();
                  if (tagSet.has(tag)) {
                    const n = (name||'').toLowerCase();
                    if ((tag==='IMG' && (n==='src' || n==='data-src')) || (tag==='SOURCE' && (n==='src' || n==='data-src'))) remember(this, value, 'src');
                    if ((tag==='IMG' && (n==='srcset' || n==='data-srcset')) || (tag==='SOURCE' && (n==='srcset' || n==='data-srcset'))) {
                      const p = pickFromSrcset(String(value||'')); if (p) remember(this, p, 'srcset');
                    }
                  }
                  return orig.apply(this, arguments);
                };
              };

              patchAttr(Element.prototype, new Set(['IMG','SOURCE']));

              const desc = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, 'src');
              if (desc && desc.set) {
                Object.defineProperty(HTMLImageElement.prototype, 'src', {
                  get: desc.get,
                  set: function(v){ try{ remember(this, v, 'src'); }catch(e){} return desc.set.call(this, v); }
                });
              }

              const mo = new MutationObserver(list=>{
                for(const m of list){
                  const el = m.target;
                  if (!(el instanceof HTMLElement)) continue;
                  const tag = el.tagName;
                  if (tag==='IMG' || tag==='SOURCE'){
                    if (m.type==='attributes'){
                      const n = (m.attributeName||'').toLowerCase();
                      if (n==='src' || n==='data-src'){
                        remember(el, el.getAttribute(n), 'src');
                      } else if (n==='srcset' || n==='data-srcset'){
                        const p = pickFromSrcset(el.getAttribute(n)||''); if (p) remember(el, p, 'srcset');
                      }
                    }
                  }
                }
              });
              mo.observe(document.documentElement, {subtree:true, attributes:true, attributeFilter:['src','srcset','data-src','data-srcset']});

              window.__forceFixImages__ = () => {
                document.querySelectorAll('picture').forEach(p=>{
                  let best=null;
                  p.querySelectorAll('source').forEach(s=>{
                    const rec = window.__imgSeen__.get(s);
                    if (rec && rec.best) best = rec.best;
                    if (!best){
                      const ss = s.getAttribute('srcset') || s.getAttribute('data-srcset');
                      const pick = pickFromSrcset(ss||''); if (pick) best = abs(pick) || best;
                    }
                  });
                  const img = p.querySelector('img');
                  if (img && best){
                    img.setAttribute('src', best);
                    img.removeAttribute('srcset');
                    img.removeAttribute('data-src'); img.removeAttribute('data-srcset');
                    let rec = window.__imgSeen__.get(img) || {};
                    rec.best = best; window.__imgSeen__.set(img, rec);
                  }
                });

                document.querySelectorAll('img').forEach(img=>{
                  const rec = window.__imgSeen__.get(img) || {};
                  const cur = img.getAttribute('src') || '';
                  const bad = cur==='//:0' || cur==='https://:0' || cur==='http://:0' || cur==='' || /^https?:\\/\\/?:0$/.test(cur);
                  const cand = rec.best || img.currentSrc || img.getAttribute('data-src') || img.getAttribute('src') || '';
                  let final = cand;
                  if (!final){
                    const ss = img.getAttribute('srcset') || img.getAttribute('data-srcset') || '';
                    const p = pickFromSrcset(ss); if (p) final = abs(p);
                  }
                  if (bad && final){
                    img.setAttribute('src', final);
                  }
                  if (img.classList.contains('v-lazy-image')){
                    img.loading = 'eager';
                    img.decoding = 'sync';
                    img.removeAttribute('data-src'); img.removeAttribute('data-srcset'); img.removeAttribute('srcset');
                  }
                });

                document.querySelectorAll('[style*="background"]').forEach(el=>{
                  const bg = getComputedStyle(el).backgroundImage||'';
                  const m = bg.match(/url\\((["']?)([^"')]+)\\1\\)/g)||[];
                  m.forEach(u=>{
                    const mm=u.match(/url\\((["']?)([^"')]+)\\1\\)/); if(!mm||!mm[2]) return;
                    const a = abs(mm[2]);
                    if (a && !/^https?:\\/\\/?:0$/.test(a)) {
                      const img = new Image(); img.src = a;
                    }
                  });
                });
              };
            })();
        """
    })
    return d

def wait_for_network_idle_and_images(driver, min_quiet_ms=1500, max_wait_s=60):
    t0 = time.time()
    last_change = time.time()
    last_counts = (-1, -1, -1)
    while True:
        try:
            active = driver.execute_script("return (window.__activeXHR__||0)+(window.__activeFetch__||0)")
        except:
            active = 0
        imgs = driver.execute_script("return {t: document.images.length, r: Array.from(document.images).filter(i=>i.complete&&i.naturalWidth>0).length}")
        perf = driver.execute_script("return (performance.getEntriesByType('resource')||[]).length")
        counts = (active, imgs["r"], perf)
        if counts != last_counts:
            last_counts = counts
            last_change = time.time()
        if active == 0 and (time.time() - last_change)*1000 >= min_quiet_ms:
            break
        if time.time() - t0 > max_wait_s:
            break
        driver.execute_script("window.dispatchEvent(new Event('scroll'));window.dispatchEvent(new Event('resize'));")
        time.sleep(0.25)

def hydrate_and_fix(driver):
    driver.execute_script("window.__forceFixImages__ && window.__forceFixImages__();")

def load_page_fully(driver, url):
    logging.info(f"[NAV] {url}")
    driver.get(url)
    WebDriverWait(driver, 120).until(lambda d: d.execute_script("return document.readyState")=="complete")
    last_h = 0
    stable = 0
    for _ in range(80):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(0.35)
        h = driver.execute_script("return document.body.scrollHeight||0")
        if h == last_h:
            stable += 1
        else:
            stable = 0
            last_h = h
        if stable >= 6:
            break
    wait_for_network_idle_and_images(driver, min_quiet_ms=1500, max_wait_s=60)
    hydrate_and_fix(driver)
    wait_for_network_idle_and_images(driver, min_quiet_ms=800, max_wait_s=20)
    time.sleep(10)
    hydrate_and_fix(driver)
    html = driver.page_source
    logging.info(f"[DOM] got html {len(html)} bytes from {url}")
    return html

def collect_dom_script_like_urls(driver, base_url):
    try:
        urls = driver.execute_script("""
            const out=[];
            document.querySelectorAll('script[src]').forEach(s=>out.push(s.src));
            document.querySelectorAll('link[rel=modulepreload][href]').forEach(l=>out.push(l.href));
            document.querySelectorAll('link[rel=prefetch][href]').forEach(l=>out.push(l.href));
            document.querySelectorAll('link[rel=preload][href]').forEach(l=>out.push(l.href));
            document.querySelectorAll('img[src]').forEach(i=>out.push(i.src));
            document.querySelectorAll('source[src]').forEach(s=>out.push(s.src));
            document.querySelectorAll('[style*="background"]').forEach(el=>{
                const bg=getComputedStyle(el).backgroundImage||'';
                const m=bg.match(/url\\((["']?)([^"')]+)\\1\\)/g)||[];
                m.forEach(u=>{
                    const mm=u.match(/url\\((["']?)([^"')]+)\\1\\)/);
                    if(mm&&mm[2]) out.push(mm[2]);
                });
            });
            return out;
        """)
    except:
        urls = []
    out = set()
    for u in urls:
        au = absolutize(u, base_url)
        if au and is_same_origin(au) and want_any(au):
            out.add(au)
    logging.info(f"[DOM-SCRIPTS] {len(out)} urls")
    return out

def collect_perf_urls(driver, base_url):
    try:
        entries = driver.execute_script("return (performance.getEntriesByType('resource')||[]).map(e=>({name:e.name, type:e.initiatorType}))")
    except:
        entries = []
    out = set()
    for e in entries:
        u = e.get("name")
        au = absolutize(u, base_url)
        if au and is_same_origin(au) and want_any(au):
            out.add(au)
    logging.info(f"[PERF] {len(out)} resources")
    return out

def extract_importmap_urls(html, base_url):
    out = set()
    rx = re.compile(r'<script\b[^>]*\btype=["\']importmap["\'][^>]*>(.*?)</script>', re.I|re.S)
    for m in rx.finditer(html):
        try:
            data = json.loads(m.group(1))
            imps = data.get("imports") or {}
            for _, v in imps.items():
                au = absolutize(str(v), base_url)
                if au and is_same_origin(au) and want_extension_js(au):
                    out.add(au)
        except:
            pass
    return out

def extract_from_html(text, base_url):
    out = set()
    for rx, group in HTML_ATTR_RES:
        for m in rx.finditer(text):
            val = m.group(group)
            if val is None:
                continue
            if "srcset" in rx.pattern:
                for u in (v.strip() for v in (val or "").split(",")):
                    if not u: continue
                    au = absolutize(u.split()[0], base_url)
                    if au and is_same_origin(au) and want_any(au):
                        out.add(au)
            else:
                au = absolutize(val, base_url)
                if au and is_same_origin(au) and want_any(au):
                    out.add(au)
    out |= extract_importmap_urls(text, base_url)
    logging.info(f"[PARSE-HTML] found {len(out)} urls from {base_url}")
    return out

def extract_from_css(text, base_url):
    out = set()
    for m in CSS_URL_RE.finditer(text):
        u = m.group(1) or m.group(2)
        if not u or u.startswith("data:"):
            continue
        au = absolutize(u, base_url)
        if au and is_same_origin(au) and want_extension_css(au):
            out.add(au)
    return out

def extract_from_js(text, base_url):
    out = set()
    for rx in JS_PATTERNS:
        for m in rx.finditer(text):
            u = m.group(1)
            if not u or "<" in u or ">" in u or "\n" in u or "\r":
                continue
            au = absolutize(u, base_url)
            if au and is_same_origin(au) and want_extension_js(au):
                out.add(au)
    for m in GEN_STR_URL_RE.finditer(text):
        u = m.group(0).strip('"\'')

        au = absolutize(u, base_url)
        if au and is_same_origin(au) and want_extension_js(au):
            out.add(au)
    return out

def extract_from_json_like(text, base_url):
    out = set()
    for m in GEN_STR_URL_RE.finditer(text):
        u = m.group(0).strip('"\'')

        au = absolutize(u, base_url)
        if au and is_same_origin(au) and want_extension_jsonlike(au):
            out.add(au)
    return out

def process_url(url, seen, queue, driver):
    if url in seen:
        return
    seen.add(url)
    lp = local_path_for(url)
    kind = sniff_kind_by_url(url)
    logging.info(f"[PROCESS] {url} → {lp} [{kind}]")
    if kind == "html":
        try:
            html = load_page_fully(driver, url)
            save_text_html(lp, html)
            seeds = extract_from_html(html, url)
            seeds = {absolutize(u, url) for u in seeds}
            seeds = {u for u in seeds if u and is_same_origin(u) and want_any(u)}
            queue.update(seeds)
            queue.update(collect_perf_urls(driver, url))
            queue.update(collect_dom_script_like_urls(driver, url))
        except Exception as e:
            logging.error(f"[HTML-ERR] {url} :: {e}")
            return
    else:
        try:
            r = fetch(url)
        except Exception:
            if kind == "js":
                alt_url, alt_resp = try_js_fallbacks(url)
                if alt_resp is None:
                    return
                url = alt_url
                lp = local_path_for(url)
                r = alt_resp
            else:
                return
        ct = r.headers.get("Content-Type","").split(";")[0].strip().lower()
        raw = r.content
        if is_text_content(ct, raw[:4096]):
            try:
                text = raw.decode("utf-8")
            except:
                try:
                    text = raw.decode("latin-1")
                except:
                    save_bytes(lp, raw, "bin")
                    return
            k = sniff_kind_by_ct(ct) or sniff_kind_by_url(url)
            save_text_generic(lp, text, k)
            parse_and_enqueue(url, text, queue, content_type=ct)
        else:
            save_bytes(lp, raw, ct or "bin")

def bootstrap_from_remote_index(driver):
    html = load_page_fully(driver, BASE_HTML)
    save_text_html(ROOT_HTML, html)
    seeds = extract_from_html(html, BASE_HTML)
    seeds = {absolutize(u, BASE_HTML) for u in seeds}
    seeds = {u for u in seeds if u and is_same_origin(u) and want_any(u)}
    seeds |= collect_perf_urls(driver, BASE_HTML)
    seeds |= collect_dom_script_like_urls(driver, BASE_HTML)
    return set(seeds)

def main():
    setup_logging()
    driver = init_driver()
    try:
        queue = bootstrap_from_remote_index(driver)
        logging.info(f"[QUEUE] seeded {len(queue)} urls")
        seen = set()
        while queue:
            url = queue.pop()
            process_url(url, seen, queue, driver)
    finally:
        try:
            driver.quit()
        except:
            pass
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(REWRITE_REPORT, f, ensure_ascii=False, indent=2)
        logging.info(f"=== crawl done === wrote {REPORT_PATH}")

if __name__ == "__main__":
    main()
