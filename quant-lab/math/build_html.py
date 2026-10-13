"""把 math/ 裡的五份講義轉成一個手機好讀的 HTML 檔（解答預設收起來）。

執行：uv run --with markdown python math/build_html.py
輸出：math/handouts.html
"""

import html
import re
from pathlib import Path

import markdown

root = Path(__file__).resolve().parent
out = root / "handouts.html"
files = ["01_returns_and_risk.md","02_backtest.md","03_indicators.md","04_overfitting.md","05_portfolio.md"]
sections, toc = [], []
for i, f in enumerate(files, 1):
    text = (root / f).read_text()
    text = re.sub(r"\[([^\]]+)\]\([^)]+\.md\)", r"\1", text)
    title = text.splitlines()[0].lstrip("# ").strip()
    body = markdown.markdown(text, extensions=["tables", "fenced_code"])
    body = re.sub(r"<h1>.*?</h1>", "", body, count=1)
    # 把「解答」那一節收進 <details>
    m = re.search(r"<h2>解答</h2>(.*)$", body, re.S)
    if m:
        body = body[: m.start()] + f'<details class="answers"><summary>看解答</summary>{m.group(1)}</details>'
    sid = f"h{i}"
    toc.append(f'<a href="#{sid}"><span class="n">{i:02d}</span>{html.escape(title.split("：",1)[-1])}</a>')
    sections.append(f'<section id="{sid}"><div class="eyebrow">講義 {i:02d}</div><h1>{html.escape(title.split("：",1)[-1])}</h1>{body}<p class="top"><a href="#top">回到目錄 ↑</a></p></section>')

page = f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>量化數學講義</title>
<style>
:root{{--bg:#f7f6f2;--surface:#fff;--ink:#1a1917;--ink2:#55534f;--muted:#8a8780;--line:#e2e0d8;--accent:#1c5cab;--soft:#e8f0fb;--code:#f1efe8;}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#121211;--surface:#1b1b1a;--ink:#efeee9;--ink2:#c2c0b8;--muted:#8a8780;--line:#2d2d2a;--accent:#6da7ec;--soft:#1e2b3d;--code:#232321;}}}}
:root[data-theme=dark]{{--bg:#121211;--surface:#1b1b1a;--ink:#efeee9;--ink2:#c2c0b8;--muted:#8a8780;--line:#2d2d2a;--accent:#6da7ec;--soft:#1e2b3d;--code:#232321;}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.8 -apple-system,"PingFang TC","Noto Sans TC","Microsoft JhengHei",sans-serif}}
.wrap{{max-width:760px;margin:0 auto;padding:0 16px 80px}}
header{{padding:40px 0 20px;border-bottom:1px solid var(--line)}}
header h1{{font-size:2rem;margin:0 0 8px}}
header p{{color:var(--ink2);margin:0 0 6px}}
.note{{font-size:.85rem;color:var(--ink2);border-left:3px solid #e0703a;padding:4px 12px;margin-top:14px;background:var(--surface)}}
nav{{display:grid;gap:8px;margin:20px 0 8px}}
nav a{{display:flex;gap:12px;align-items:center;padding:12px 14px;border:1px solid var(--line);border-radius:10px;background:var(--surface);color:var(--ink);text-decoration:none;font-weight:500}}
nav .n{{font:500 .85rem ui-monospace,Menlo,monospace;color:var(--accent)}}
section{{padding-top:36px;border-top:1px solid var(--line);margin-top:36px}}
.eyebrow{{font:500 .75rem ui-monospace,Menlo,monospace;letter-spacing:.12em;color:var(--muted)}}
section>h1{{font-size:1.7rem;margin:4px 0 12px}}
h2{{font-size:1.25rem;margin:32px 0 8px;padding-top:8px}}
h3{{font-size:1.05rem;margin:22px 0 6px}}
p{{margin:0 0 12px}}
a{{color:var(--accent)}}
pre{{background:var(--code);border-radius:8px;padding:12px 14px;overflow-x:auto;white-space:pre-wrap;word-break:break-word;font-size:.9rem;line-height:1.6;margin:10px 0 14px}}
code{{font-family:ui-monospace,Menlo,monospace;font-size:.9em}}
p code,li code,td code{{background:var(--code);padding:1px 5px;border-radius:4px}}
.tbl{{overflow-x:auto;margin:10px 0 16px}}
table{{border-collapse:collapse;width:100%;font-size:.92rem;background:var(--surface)}}
th,td{{border-bottom:1px solid var(--line);padding:7px 10px;text-align:left;white-space:nowrap}}
th{{color:var(--muted);font-weight:500;font-size:.82rem}}
blockquote{{margin:12px 0;padding:6px 14px;border-left:3px solid var(--accent);background:var(--soft);border-radius:4px}}
hr{{border:0;border-top:1px dashed var(--line);margin:28px 0}}
ol,ul{{padding-left:1.4em}} li{{margin:4px 0}}
details.answers{{margin:16px 0;border:1px solid var(--line);border-radius:10px;background:var(--surface)}}
details.answers summary{{cursor:pointer;padding:12px 16px;font-weight:600;color:var(--accent);list-style:none}}
details.answers summary::before{{content:"▸ ";}}
details.answers[open] summary::before{{content:"▾ ";}}
details.answers>*:not(summary){{margin-left:16px;margin-right:16px}}
details.answers ol{{padding-bottom:10px}}
.top{{text-align:right;font-size:.85rem;margin-top:20px}}
</style></head>
<body><div class="wrap" id="top">
<header>
<h1>量化數學講義</h1>
<p>課程程式只印出算好的答案，這份講義教你那些數字怎麼算出來。</p>
<p>每份都有：公式、白話解釋、手算例題、練習題。解答收起來了，先自己算再點開。</p>
<div class="note">僅供學習，非投資建議。需要的數學只有加減乘除、百分比、次方、開根號；手機計算機橫過來就有，ln 和 eˣ 也在裡面。</div>
</header>
<nav>{''.join(toc)}</nav>
{''.join(sections)}
</div></body></html>"""
page = re.sub(r"<table>", '<div class="tbl"><table>', page).replace("</table>", "</table></div>")
out.write_text(page)
print(out, len(page))
