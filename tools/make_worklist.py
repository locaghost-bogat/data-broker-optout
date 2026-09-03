#!/usr/bin/env python3
"""Emit a per-person data-broker opt-out worklist (CSV + HTML) from brokers.json.

    python3 tools/make_worklist.py --name "Andrii Bogatyrov" --born 1979 \
        --location "Raleigh, NC 27614" --aliases "Andrii/Andrey/Andrew Bogatyrov"

Nothing is sent or scanned -- this is the list of every broker plus its site and
privacy/opt-out contact, to work down with the app's "Prepare request" button.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import html
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brokers", type=Path, default=REPO_ROOT / "brokers.json")
    ap.add_argument("--out-dir", type=Path, default=REPO_ROOT / "out")
    ap.add_argument("--name", required=True)
    ap.add_argument("--born", default="")
    ap.add_argument("--location", default="")
    ap.add_argument("--aliases", default="")
    a = ap.parse_args()

    data = json.loads(a.brokers.read_text(encoding="utf-8"))
    brokers = sorted(data["brokers"], key=lambda b: b["name"].lower())
    a.out_dir.mkdir(parents=True, exist_ok=True)
    slug = "".join(c for c in a.name if c.isalnum())

    rows = [{
        "name": b["name"],
        "site": b.get("site") or "",
        "opt_out_url": b.get("opt_out_url") or "",
        "email": b.get("privacy_email") or "",
        "phone": b.get("privacy_phone") or "",
        "method": b.get("method") or "",
        "source": b.get("source") or "",
    } for b in brokers]
    with_email = sum(1 for r in rows if r["email"])

    csv_path = a.out_dir / f"opt-out-worklist_{slug}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["#", "Broker Name", "Site", "Opt-out / privacy URL", "Email", "Phone", "Method", "Source"])
        for i, r in enumerate(rows, 1):
            w.writerow([i, r["name"], r["site"], r["opt_out_url"], r["email"], r["phone"], r["method"], r["source"]])

    esc = html.escape
    trs = []
    for i, r in enumerate(rows, 1):
        link = r["opt_out_url"] or r["site"]
        shown = link.replace("https://", "").replace("http://", "")[:64]
        site_cell = f'<a href="{esc(link)}" target="_blank" rel="noopener">{esc(shown)}</a>' if link else ""
        mail_cell = (f'<a href="mailto:{esc(r["email"])}">{esc(r["email"])}</a>'
                     if r["email"] else '<span class="muted">web form</span>')
        trs.append(f"<tr><td>{i}</td><td>{esc(r['name'])}</td><td>{site_cell}</td>"
                   f"<td>{mail_cell}</td><td>{esc(r['method'])}</td></tr>")

    doc = f"""<!doctype html><meta charset="utf-8">
<title>Opt-out worklist - {esc(a.name)}</title>
<style>
 body{{font:14px -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;margin:24px;color:#1a1a1a}}
 h1{{font-size:19px;margin:0 0 2px}} .sub{{color:#666;margin-bottom:14px;line-height:1.5}}
 input{{padding:7px 10px;font-size:14px;width:280px;margin-bottom:12px;border:1px solid #ccc;border-radius:6px}}
 table{{border-collapse:collapse;width:100%}}
 th,td{{text-align:left;padding:6px 10px;border-bottom:1px solid #eee;vertical-align:top}}
 th{{position:sticky;top:0;background:#fafafa;border-bottom:2px solid #ddd;cursor:pointer}}
 tr:hover td{{background:#f7fbff}} td:first-child{{color:#999}} .muted{{color:#aaa}}
 a{{color:#0a5bd3;text-decoration:none}} a:hover{{text-decoration:underline}}
</style>
<h1>Data-broker opt-out worklist</h1>
<div class="sub"><b>{esc(a.name)}</b> &nbsp;b. {esc(a.born)} &nbsp;·&nbsp; {esc(a.location)} &nbsp;·&nbsp; aka {esc(a.aliases)}<br>
{len(rows)} brokers &nbsp;·&nbsp; {with_email} with a direct email &nbsp;·&nbsp; {len(rows) - with_email} web-form only
&nbsp;·&nbsp; generated {datetime.date.today().isoformat()}</div>
<input id="q" placeholder="filter by broker name..." oninput="flt()">
<table id="t"><thead><tr><th>#</th><th onclick="srt(1)">Broker</th><th>Site / opt-out link</th>
<th>Email</th><th onclick="srt(4)">Method</th></tr></thead>
<tbody>{''.join(trs)}</tbody></table>
<script>
 const t=document.getElementById('t');
 function flt(){{const v=document.getElementById('q').value.toLowerCase();
  for(const r of t.tBodies[0].rows)r.style.display=r.cells[1].textContent.toLowerCase().includes(v)?'':'none';}}
 function srt(i){{const rs=[...t.tBodies[0].rows];
  rs.sort((a,b)=>a.cells[i].textContent.localeCompare(b.cells[i].textContent));
  rs.forEach(r=>t.tBodies[0].appendChild(r));}}
</script>
"""
    html_path = a.out_dir / f"opt-out-worklist_{slug}.html"
    html_path.write_text(doc, encoding="utf-8")

    print(f"{len(rows)} brokers | {with_email} with email | {len(rows) - with_email} form-only")
    print("wrote", csv_path)
    print("wrote", html_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
