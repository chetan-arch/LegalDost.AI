"""Local development chat simulator. Disabled when ENVIRONMENT=production."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from legaldost.api.processing import process_text
from legaldost.api.services import Services

router = APIRouter(prefix="/dev", tags=["dev"])


class ChatIn(BaseModel):
    session_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    message: str = Field(max_length=4000)


class ChatOut(BaseModel):
    reply: str
    outcome: str
    evidence_status: str | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)
    validation_flags: list[str] = Field(default_factory=list)
    routing: dict[str, Any] | None = None
    diagnostics: dict[str, Any] = Field(default_factory=dict)


def _services(request: Request) -> Services:
    services: Services = request.app.state.services
    if services.settings.environment == "production":
        raise HTTPException(status_code=404)
    return services


@router.post("/chat", response_model=ChatOut)
def chat(body: ChatIn, request: Request) -> ChatOut:
    services = _services(request)
    reply = process_text(services, "dev", body.session_id, body.message)
    answer = reply.answer
    return ChatOut(
        reply=reply.text,
        outcome=reply.outcome,
        evidence_status=answer.evidence_status.value if answer and answer.kind == "answer" else None,
        sources=[c.model_dump(mode="json") for c in answer.supporting_sources] if answer else [],
        validation_flags=list(answer.validation.flags) if answer else [],
        routing=reply.routing.model_dump() if reply.routing else None,
        diagnostics=reply.diagnostics,
    )


@router.get("", response_class=HTMLResponse)
def page(request: Request) -> str:
    _services(request)
    return DEV_PAGE


DEV_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LegalDost dev chat</title>
<style>
:root{--bg:#efeae2;--me:#d9fdd3;--bot:#fff;--ink:#111b21;--muted:#667781;--accent:#008069;--link:#027eb5}
@media (prefers-color-scheme:dark){:root{--bg:#0b141a;--me:#005c4b;--bot:#202c33;--ink:#e9edef;--muted:#8696a0;--link:#53bdeb}}
a{color:var(--link);word-break:break-all}
*{box-sizing:border-box}body{margin:0;font:15px/1.45 system-ui,sans-serif;background:var(--bg);color:var(--ink);
display:flex;flex-direction:column;height:100vh}
header{background:var(--accent);color:#fff;padding:10px 16px;font-weight:600}
header small{font-weight:400;opacity:.85;margin-left:8px}
#log{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:8px}
.m{max-width:min(680px,88%);padding:8px 12px;border-radius:8px;white-space:pre-wrap;word-wrap:break-word}
.me{align-self:flex-end;background:var(--me)}.bot{align-self:flex-start;background:var(--bot)}
.meta{font-size:12px;color:var(--muted);margin-top:4px}
form{display:flex;gap:8px;padding:10px 16px;background:var(--bot)}
input{flex:1;padding:10px;border-radius:20px;border:1px solid var(--muted);background:var(--bg);color:var(--ink)}
button{border:0;border-radius:20px;padding:0 18px;background:var(--accent);color:#fff;font-weight:600}
</style></head><body>
<header>LegalDost <small>local simulator: same pipeline as WhatsApp, no Meta credentials</small></header>
<div id="log"></div>
<form id="f"><input id="q" autocomplete="off" placeholder="Describe your situation… (try: help, more, sources)">
<button>Send</button></form>
<script>
const sid=(()=>{try{let s=localStorage.getItem('ld_sid');if(!s){s='dev-'+Math.random().toString(36).slice(2,10);
localStorage.setItem('ld_sid',s)}return s}catch(e){return 'dev-'+Math.random().toString(36).slice(2,10)}})();
const log=document.getElementById('log');
function fmt(t){const e=document.createElement('div');e.textContent=t;return e.innerHTML
.replace(/\\*([^*\\n]+)\\*/g,'<b>$1</b>').replace(/(^|\\s)_([^_\\n]+)_/g,'$1<i>$2</i>')
.replace(/(https:\\/\\/[^\\s<]+)/g,'<a href="$1" target="_blank" rel="noopener">$1</a>')}
function add(cls,html,meta){const d=document.createElement('div');d.className='m '+cls;d.innerHTML=html;
if(meta){const m=document.createElement('div');m.className='meta';m.textContent=meta;d.appendChild(m)}
log.appendChild(d);log.scrollTop=log.scrollHeight}
document.getElementById('f').onsubmit=async e=>{e.preventDefault();const q=document.getElementById('q');
const text=q.value.trim();if(!text)return;q.value='';add('me',fmt(text));
try{const r=await fetch('/dev/chat',{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify({session_id:sid,message:text})});const j=await r.json();
if(!r.ok){add('bot',fmt(JSON.stringify(j)));return}
const meta=[j.outcome,j.evidence_status,j.routing&&j.routing.engine,(j.diagnostics||{}).latency_ms+' ms',
(j.validation_flags||[]).join(',')].filter(Boolean).join(' · ');add('bot',fmt(j.reply),meta)}
catch(err){add('bot','Request failed: '+err)}};
</script></body></html>"""
