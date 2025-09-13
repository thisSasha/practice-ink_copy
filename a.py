#!/usr/bin/env python3
import os, re

PATTERN = re.compile(
    r'(<a[^>]*class="[^"]*\bbrand\b[^"]*"[^>]*>)\s*'
    r'<span[^>]*>\s*<svg.*?</svg>\s*</span>\s*'
    r'<span[^>]*>\s*<svg.*?</svg>\s*</span>\s*'
    r'</a>',
    re.IGNORECASE | re.DOTALL,
)

REPLACEMENT = r'''\1
  <h3 class="text-green" style="font-size: 40px;">Leaderring</h3>
</a>'''

def process_text(txt):
    return PATTERN.sub(REPLACEMENT, txt)

def read_text(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def write_text(path, txt):
    with open(path, "w", encoding="utf-8") as f:
        f.write(txt)

def is_html(path):
    return os.path.splitext(path)[1].lower() in {".html",".htm",".shtml",".xhtml"}

def main():
    changed = []
    for root, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if d not in {".git","node_modules",".venv","venv",".next",".cache","dist","build","out"}]
        for fn in files:
            p = os.path.join(root, fn)
            if not is_html(p): continue
            try: txt = read_text(p)
            except Exception: continue
            new = process_text(txt)
            if new != txt:
                write_text(p, new)
                changed.append(p)
    if changed:
        print(f"заменено в {len(changed)} файлах")
    else:
        print("ничего не нашёл.")

if __name__ == "__main__":
    main()
