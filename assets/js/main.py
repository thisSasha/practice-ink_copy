import re, sys, shutil, time, pathlib

p = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "main.js")
src = p.read_text(encoding="utf-8")
bak = p.with_suffix(p.suffix + f".bak.{int(time.time())}")
shutil.copyfile(p, bak)

t = src

def ensure_getMenu(text):
    if "const getMenu =" in text:
        return text
    # вставляем сразу после первого упоминания body/document.body, иначе — в начало
    m = re.search(r"(const\s+body\s*=\s*document\.body\s*;?)", text)
    inject = "\nconst getMenu = () => document.querySelector('menu, .eo-mobile-menu, [data-menu]')\n"
    if m:
        i = m.end()
        return text[:i] + inject + text[i:]
    return inject + text

t = ensure_getMenu(t)

t = re.sub(
    r"""function\s+openMenu\s*\(\)\s*{.*?}""",
    """function openMenu() {
  const m = getMenu(); if(!m) return
  document.body.classList.add('overflow-hidden')
  m.classList.remove('-translate-x-fuller')
  m.classList.add('translate-x-0')
  if (typeof tintLeftBarGreen==='function') tintLeftBarGreen(true)
  if (typeof toggleIcons==='function') toggleIcons()
}""",
    t, count=1, flags=re.S
)

t = re.sub(
    r"""function\s+closeMenu\s*\(\)\s*{.*?}""",
    """function closeMenu() {
  const m = getMenu(); if(!m) return
  document.body.classList.remove('overflow-hidden')
  m.classList.add('-translate-x-fuller')
  m.classList.remove('translate-x-0')
  if (typeof tintLeftBarGreen==='function') tintLeftBarGreen(false)
  if (typeof toggleIcons==='function') toggleIcons()
}""",
    t, count=1, flags=re.S
)

# выпиливаем ВСЕ старые onclick на .nav-button
t = re.sub(
    r"""document\.querySelector\(\s*['"]\.nav-button['"]\s*\)\.onclick\s*=\s*function\s*\([^)]*\)\s*{.*?};""",
    """(()=>{ const btn=document.querySelector('.nav-button'); if(!btn) return; btn.addEventListener('click',()=>{ const m=getMenu(); if(!m) return; const closed=!m.classList.contains('translate-x-0'); closed?openMenu():closeMenu() }) })()""",
    t, flags=re.S
)

# чиним блок "menu a"
t = re.sub(
    r"""document\.querySelectorAll\(\s*['"]menu\s+a['"]\s*\)\.forEach\(\s*function\s*\(el\)\s*{.*?}\s*\);\s*""",
    """;(()=>{ const root=getMenu(); if(!root) return; root.querySelectorAll('a').forEach(el=>{ el.addEventListener('click',()=>{ if(root.classList.contains('translate-x-0')) closeMenu() }) }) })()""",
    t, flags=re.S
)

# чиним блок brandText (любую версию)
brand_safe = r"""(function(){ 
  const el = document.getElementById("brandText"); 
  if(!el) return; 
  const colors = ["#2e8b57", "#2563eb", "#b22222", "#daa520"]; 
  const text = (el.textContent||"").trim(); 
  el.innerHTML = ""; 
  for(let i=0;i<text.length;i++){ const span=document.createElement("span"); span.textContent=text[i]; span.style.color=colors[i%colors.length]; el.appendChild(span) } 
  function fitText(){ el.style.fontSize="200px" } 
  fitText(); 
  window.addEventListener("resize", fitText); 
})();"""

# 1) если есть точный старый блок — заменяем
t_new = re.sub(
    r"""const\s+colors\s*=\s*\[[^\]]+\]\s*;\s*(?:\/\/[^\n]*\n)?\s*const\s+el\s*=\s*document\.getElementById\(\s*["']brandText["']\s*\)\s*;.*?window\.addEventListener\(\s*["']resize["']\s*,\s*fitText\s*\)\s*;""",
    brand_safe,
    t, flags=re.S
)
# 2) если встречается просто упоминание brandText-блока, но другой формы — грубее: всё от первой строки с getElementById до resize
t = re.sub(
    r"""const\s+el\s*=\s*document\.getElementById\(\s*["']brandText["']\s*\)\s*;.*?window\.addEventListener\(\s*["']resize["']\s*,\s*fitText\s*\)\s*;""",
    brand_safe,
    t_new, flags=re.S
)

# подстраховка: если где-то остался прямой доступ к m.classList в замыкании onclick — пытаемся локально обезвредить самые частые случаи
t = re.sub(
    r"""(\bconst\s+closed\s*=\s*!\s*)m(\.classList\.contains\(['"]translate-x-0['"]\)\s*;)""",
    r"""\1(getMenu()||{})\2""",
    t
)

if t == src:
    print("ничего не поменял — файл уже (вроде) чинный. проверь строки 48 и 1048 руками.")
else:
    p.write_text(t, encoding="utf-8")
    print(f"готово. резервная копия: {bak}")
