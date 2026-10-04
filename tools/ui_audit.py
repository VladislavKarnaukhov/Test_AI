"""Аудит интерфейса: наложение текста друг на друга, выход за край экрана и обрезанный текст.

Страницы рендерятся тестовым клиентом Flask (отдельная временная БД), затем открываются в Chrome
в iframe шириной 320–1440 px; скрипт считает пересечения текстовых блоков. Новых зависимостей нет:
нужен установленный Google Chrome (путь можно задать переменной CHROME).

Запуск из корня проекта:
    python tools/ui_audit.py                       # все страницы, стандартные ширины
    python tools/ui_audit.py home,dash 375,1440    # выбранные страницы и ширины
    python tools/ui_audit.py -v                    # подробности найденных проблем

Код возврата 1, если найдены наложения или выход за край (удобно для CI).
Статика берётся с локального сервера (python run.py на порту 5050) — он нужен для шрифтов и картинок.
Таблицы внутри .table-wrap прокручиваются по горизонтали намеренно и не считаются ошибкой.
"""
import html as htmllib
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.consent import POLICY_VERSION  # noqa: E402
from tests.answers import SHORT_EXAMPLE, medium, short, with_consent  # noqa: E402

CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
SERVER = os.environ.get("AUDIT_SERVER", "http://localhost:5050/")
WIDTHS = [320, 375, 390, 430, 768, 1024, 1440]

AUDIT_JS = r"""
function audit(doc, W){
  const st=doc.createElement('style'); st.textContent='*,*::before,*::after,*::details-content{animation:none!important;transition:none!important}'; doc.head.appendChild(st);
  const win=doc.defaultView; const out={w:W,overflow:[],overlaps:[],clipped:[]};
  const rects=[]; const walker=doc.createTreeWalker(doc.body,NodeFilter.SHOW_TEXT);
  let n; while(n=walker.nextNode()){
    if(!n.nodeValue.trim()) continue; const el=n.parentElement; if(!el) continue;
    if(el.closest('[hidden],script,style,noscript,.visually-hidden,[aria-hidden=true]:not(svg text)')) continue;
    const cs=win.getComputedStyle(el); if(cs.display==='none'||cs.visibility==='hidden'||parseFloat(cs.opacity)===0) continue;
    if(el.closest('dialog:not([open])')||el.closest('details:not([open]) > :not(summary)')) continue;
    const r=doc.createRange(); r.selectNodeContents(n);
    for(const b of r.getClientRects()){ if(b.width>1&&b.height>1) rects.push({b,el,t:n.nodeValue.trim().slice(0,28)}); }
  }
  const docW=doc.documentElement.clientWidth;
  for(const r of rects){ if((r.b.right>docW+1||r.b.left<-1)&&!r.el.closest('.table-wrap,.ticker')) out.overflow.push(desc(r.el)+' '+r.t+' right='+Math.round(r.b.right)); }
  for(let i=0;i<rects.length;i++){ for(let j=i+1;j<rects.length;j++){
    const a=rects[i],b=rects[j]; if(a.el===b.el) continue;
    const ix=Math.min(a.b.right,b.b.right)-Math.max(a.b.left,b.b.left), iy=Math.min(a.b.bottom,b.b.bottom)-Math.max(a.b.top,b.b.top);
    if(ix>3&&iy>4){
      if(isFixed(a.el)!==isFixed(b.el)) continue;                                   // плавающие слои лежат поверх по замыслу
      const sameFlow=a.el.parentElement===b.el.parentElement||a.el.contains(b.el)||b.el.contains(a.el);
      if(sameFlow&&iy<0.4*Math.min(a.b.height,b.b.height)) continue;               // плотный межстрочный интервал заголовков
      out.overlaps.push(desc(a.el)+' «'+a.t+'» × '+desc(b.el)+' «'+b.t+'» '+Math.round(ix)+'x'+Math.round(iy));
    } } }
  doc.querySelectorAll('body *').forEach(e=>{ const cs=win.getComputedStyle(e); if((cs.overflow==='hidden'||cs.textOverflow==='ellipsis')&&e.scrollWidth>e.clientWidth+2&&e.textContent.trim()&&e.clientWidth>0&&!e.closest('.ticker,.range,.menu,.table-wrap,.visually-hidden')) out.clipped.push(desc(e)+' '+e.scrollWidth+'>'+e.clientWidth); });
  out.docOverflow=doc.documentElement.scrollWidth>doc.documentElement.clientWidth+1?doc.documentElement.scrollWidth:0;
  return out;
  function isFixed(e){for(let x=e;x&&x!==doc.body;x=x.parentElement){{const ps=win.getComputedStyle(x).position;if(ps==='fixed'||ps==='sticky')return true;}}return false;}
  function desc(e){return e.tagName.toLowerCase()+(e.className&&typeof e.className==='string'?'.'+e.className.trim().split(/\s+/).slice(0,2).join('.'):'');}
}
"""


def build_pages():
    app = create_app({"TESTING": True, "DATABASE_PATH": os.path.join(tempfile.mkdtemp(), "audit.db")})
    base = f'<base href="{SERVER}">'

    def client(consent="necessary"):
        c = app.test_client()
        if consent:
            c.set_cookie("vs_consent", consent)
            c.set_cookie("vs_consent_v", POLICY_VERSION)
        return c

    def csrf(c, path):
        return re.search(r'name="csrf_token" value="([^"]+)"', c.get(path).get_data(as_text=True)).group(1)

    def page(c, path, extra=""):
        return c.get(path).get_data(as_text=True).replace("<head>", "<head>" + base, 1).replace("</body>", extra + "</body>")

    guest = client()
    user = client()
    user.post("/register", data={"csrf_token": csrf(user, "/register"), "name": "Анна", "email": "audit@example.test",
                                 "password": "correct-horse-1", "password_confirm": "correct-horse-1",
                                 "consent": "on", "terms": "on"})
    for payload in (SHORT_EXAMPLE, short(n1="2", n2="7"), medium(), short(n1="2", n2="7")):
        user.post("/api/score", json=with_consent(payload))
    open_subs = '<script>addEventListener("load",function(){document.querySelectorAll(".entry[open] details.sub").forEach(function(d){d.open=true})})</script>'
    return {
        "home": page(guest, "/"),
        "home_user": page(user, "/"),
        "dash": page(user, "/account", open_subs),
        "settings": page(user, "/account/settings"),
        "login": page(guest, "/login"),
        "register": page(guest, "/register"),
        "methodology": page(guest, "/methodology"),
        "privacy": page(guest, "/privacy"),
        "terms": page(guest, "/terms"),
    }


def run_page(name, src, widths):
    frames = "".join(
        f'<iframe id="f{w}" style="width:{w}px;height:900px;border:0" srcdoc="{htmllib.escape(src, quote=True)}"></iframe>'
        for w in widths)
    wrapper = (f'<!doctype html><meta charset=utf-8><body>{frames}<pre id="out"></pre><script>{AUDIT_JS}\n'
               f'const widths={json.dumps(widths)};const results=[];let loaded=0;'
               'widths.forEach(w=>{const f=document.getElementById("f"+w);f.addEventListener("load",()=>{setTimeout(()=>{'
               'try{results.push(audit(f.contentDocument,w))}catch(e){results.push({w,err:String(e)})}'
               'loaded++;if(loaded===widths.length)document.getElementById("out").textContent="@@"+JSON.stringify(results)+"@@"},2500)})});</script>')
    path = os.path.join(tempfile.mkdtemp(), f"audit_{name}.html")
    open(path, "w", encoding="utf-8").write(wrapper)
    res = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--window-size=1600,1000", "--virtual-time-budget=25000",
                          "--dump-dom", "file://" + path], capture_output=True, text=True, timeout=300)
    found = re.findall(r"@@(\[.*?\])@@", res.stdout, re.S)
    if not found:
        raise SystemExit(f"{name}: нет результата (запущен ли сервер {SERVER} и найден ли Chrome?)")
    return sorted(json.loads(htmllib.unescape(found[-1])), key=lambda d: d["w"])


def main(argv):
    verbose = "-v" in argv
    args = [a for a in argv if a != "-v"]
    pages = build_pages()
    names = args[0].split(",") if args else list(pages)
    widths = [int(w) for w in args[1].split(",")] if len(args) > 1 else WIDTHS
    problems = 0
    for name in names:
        print(f"== {name}")
        for d in run_page(name, pages[name], widths):
            n = len(d["overlaps"]) + len(d["overflow"]) + (1 if d["docOverflow"] else 0)
            problems += n
            print(f"  {d['w']:>4}px: наложений={len(d['overlaps'])} выход за край={len(d['overflow'])} "
                  f"обрезано={len(d['clipped'])} прокрутка вбок={d['docOverflow']}")
            if verbose:
                for k in ("overlaps", "overflow", "clipped"):
                    for line in d[k][:6]:
                        print(f"        {k[:4]} {line}")
    print("Проблем:", problems)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
