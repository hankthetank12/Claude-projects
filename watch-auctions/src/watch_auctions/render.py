"""Render the catalog as one self-contained HTML page (works offline, on a phone)."""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone

from watch_auctions.models import Lot

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Watch Auctions</title>
<style>
:root{--bg:#f6f5f2;--card:#fff;--ink:#1c1c1c;--mute:#6b6b6b;--line:#e3e1dc;--acc:#1f5f4a;--new:#b4502a}
@media (prefers-color-scheme:dark){:root{--bg:#141414;--card:#1e1e1e;--ink:#eee;--mute:#9a9a9a;--line:#2e2e2e;--acc:#6fc2a2;--new:#f08b5f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.4 system-ui,-apple-system,sans-serif}
header{position:sticky;top:0;z-index:2;background:var(--bg);border-bottom:1px solid var(--line);padding:12px 16px}
h1{font-size:18px;margin:0 0 8px}h1 small{color:var(--mute);font-weight:400;font-size:13px;margin-left:6px}
.f{display:flex;flex-wrap:wrap;gap:8px}.f input,.f select{font:inherit;padding:6px 8px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink)}
.f input[type=search]{flex:1 1 220px}.f select{max-width:100%;min-width:0}
main{padding:12px 16px;max-width:1400px;margin:0 auto}
.day{margin:18px 0 8px;font-weight:600;color:var(--mute);font-size:13px;text-transform:uppercase;letter-spacing:.04em}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}
.c{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;display:flex;flex-direction:column;color:inherit;text-decoration:none}
.c img{width:100%;aspect-ratio:1;object-fit:cover;background:var(--line)}
.b{padding:8px 10px;display:flex;flex-direction:column;gap:3px;flex:1}
.t{font-weight:600;font-size:14px;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.m{color:var(--mute);font-size:12px}.p{font-size:13px;margin-top:auto;padding-top:4px}.p b{color:var(--acc)}
.tag{display:inline-block;font-size:11px;border:1px solid var(--line);border-radius:4px;padding:0 4px;margin-right:4px}
.tag.new{color:var(--new);border-color:var(--new)}
.empty{color:var(--mute);padding:40px 0;text-align:center}
@media (max-width:560px){.grid{grid-template-columns:1fr 1fr;gap:8px}.t{font-size:13px}.f select{flex:1 1 40%}}
</style></head><body>
<header><h1>Upcoming watch lots<small id="count"></small><small>updated __UPDATED__</small></h1>
<div class="f">
<input type="search" id="q" placeholder="Search title, house, reference…">
<select id="brand"><option value="">All brands</option></select>
<select id="state"><option value="">All states</option></select>
<select id="house"><option value="">All houses</option></select>
<select id="when"><option value="">Any time</option><option value="1">Next 24h</option><option value="3">Next 3 days</option><option value="7">Next 7 days</option></select>
<label class="m"><input type="checkbox" id="onlynew"> New since last run</label>
</div></header>
<main id="list"></main>
<script>
const LOTS=__DATA__;
const $=id=>document.getElementById(id);
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function fill(id,vals){const s=$(id);[...new Set(vals.filter(Boolean))].sort().forEach(v=>{const o=document.createElement("option");o.value=o.textContent=v;s.appendChild(o)})}
fill("brand",LOTS.map(l=>l.brand));fill("state",LOTS.map(l=>l.state));fill("house",LOTS.map(l=>l.house));
const money=(n,c)=>n?new Intl.NumberFormat("en-US",{style:"currency",currency:c||"USD",maximumFractionDigits:0}).format(n):"";
const when=l=>l.ends_at||l.starts_at;
const dayLabel=t=>t?new Date(t*1000).toLocaleDateString(undefined,{weekday:"long",month:"short",day:"numeric"}):"Date TBA";
const timeLabel=t=>t?new Date(t*1000).toLocaleTimeString(undefined,{hour:"numeric",minute:"2-digit"}):"";
function card(l){
  const est=l.estimate_low||l.estimate_high?`Est. ${money(l.estimate_low,l.currency)}${l.estimate_high?"–"+money(l.estimate_high,l.currency):""}`:"";
  const bid=l.current_bid?`<b>${money(l.current_bid,l.currency)}</b> · ${l.bid_count} bid${l.bid_count==1?"":"s"}`:"No bids yet";
  const verb=l.sale_type==="timed"?"Closes":"Sale";
  return `<a class="c" href="${esc(l.url)}" target="_blank" rel="noopener">
  ${l.image?`<img loading="lazy" src="${esc(l.image)}" alt="">`:`<img alt="">`}
  <div class="b"><div>${l.is_new?'<span class="tag new">new</span>':""}${l.brand?`<span class="tag">${esc(l.brand)}</span>`:""}<span class="tag">${esc(l.sale_type)}</span></div>
  <div class="t">${esc(l.title)}</div>
  <div class="m">${esc(l.house)}${l.city||l.state?` · ${esc([l.city,l.state].filter(Boolean).join(", "))}`:""}</div>
  <div class="m">${verb} ${timeLabel(when(l))}${l.lot_number?` · Lot ${esc(l.lot_number)}`:""} · via ${esc(l.source)}${l.also_on.length?" +"+l.also_on.length:""}</div>
  <div class="p">${bid}${est?`<div class="m">${est}</div>`:""}</div></div></a>`}
function render(){
  const q=$("q").value.toLowerCase().trim(),b=$("brand").value,s=$("state").value,h=$("house").value,w=+$("when").value,nw=$("onlynew").checked;
  const lim=w?Date.now()/1000+w*86400:Infinity;
  const rows=LOTS.filter(l=>(!b||l.brand===b)&&(!s||l.state===s)&&(!h||l.house===h)&&(!nw||l.is_new)&&(when(l)||0)<=lim&&
    (!q||(l.title+" "+l.house+" "+l.sale_title).toLowerCase().includes(q)));
  $("count").textContent=`${rows.length} lots`;
  if(!rows.length){$("list").innerHTML='<div class="empty">Nothing matches.</div>';return}
  let html="",day=null,open=false;
  for(const l of rows){const d=dayLabel(when(l));if(d!==day){if(open)html+="</div>";html+=`<div class="day">${d}</div><div class="grid">`;day=d;open=true}html+=card(l)}
  $("list").innerHTML=html+"</div>"}
["q","brand","state","house","when","onlynew"].forEach(id=>$(id).addEventListener("input",render));render();
</script></body></html>"""


def render(lots: list[Lot], new_ids: set[str], generated: datetime | None = None) -> str:
    generated = generated or datetime.now(timezone.utc)
    rows = []
    for l in lots:
        d = l.to_dict()
        d["is_new"] = f"{l.source}:{l.source_id}" in new_ids
        rows.append(d)
    data = json.dumps(rows, separators=(",", ":")).replace("</", "<\\/")
    return (_PAGE.replace("__UPDATED__", html.escape(generated.strftime("%b %d, %H:%M UTC")))
            .replace("__DATA__", data))
