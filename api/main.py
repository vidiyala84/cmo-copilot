"""FastAPI backend for the showcase UI.

Thin JSON wrapper over the three tracks — it imports the existing track modules
and exposes their runs as endpoints. Everything runs in mock mode (no API key),
so the UI is fully driveable offline.

Run: uvicorn api.main:app --reload --port 8000   (from the hackathon/ dir)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from cmo.config import MODELS, LLM_PROVIDER, QWEN_API_KEY, RUNS_DIR  # noqa: E402
from cmo.datagen import generate_base  # noqa: E402
from cmo.scenarios import SCENARIOS  # noqa: E402
from cmo.tools import ScenarioEnv  # noqa: E402
from cmo.harness import run as harness_run, score  # noqa: E402

UI_RUNS = RUNS_DIR / "ui"
TRAPS = {"S02", "S07", "S08", "S09"}

app = FastAPI(title="CMO Copilot — Three Architectures", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

_cache = {}


# --------------------------------------------------------------------- models

class Track1Req(BaseModel):
    sessions: int = 5
    live: bool = False


class Track4Req(BaseModel):
    scenario: str
    fault: str | None = None            # None | "api500" | "timeout"
    gate: str = "auto"                  # auto | approve | reject | adjust | expire
    live: bool = False


class LiveRunReq(BaseModel):
    scenario: str
    approach: str = "direct"            # direct | direct_rules | baseline | society
    mock: bool = True                   # True = free/deterministic (default, safe on a public URL)


# --------------------------------------------------------------------- helpers

def _scenario(sid):
    return next(s for s in SCENARIOS if s["id"] == sid)


def _results_payload(results):
    return [{"scenario": r["scenario"], "name": r["name"], "score": r["score"],
             "decision": r["decision"], "expected": r["expected"],
             "notes": r["notes"], "tool_calls": r["tool_calls"],
             "is_trap": r["scenario"] in TRAPS} for r in results]


# --------------------------------------------------------------------- landing page

INDEX_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CMO Copilot — live demo</title>
<style>
:root{color-scheme:dark}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#0b1020;color:#e7ecf5;line-height:1.5}
.wrap{max-width:1080px;margin:0 auto;padding:34px 22px 90px}
header{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
h1{font-size:27px;letter-spacing:-.02em}
.dot{display:inline-flex;align-items:center;gap:7px;font-size:13px;background:#0e1526;border:1px solid #263154;border-radius:999px;padding:5px 12px;color:#93a4c8}
.dot i{width:8px;height:8px;border-radius:50%;background:#f59e0b}
.sub{color:#9fb0d0;max-width:74ch;margin:12px 0 28px;font-size:15px}
.sub b{color:#e7ecf5}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
.card{background:#141b30;border:1px solid #263154;border-radius:14px;padding:18px;cursor:pointer;transition:.15s;position:relative}
.card:hover{border-color:#3b82f6;transform:translateY(-2px)}
.card h3{font-size:15.5px;margin-bottom:8px;padding-right:56px}
.card p{color:#93a4c8;font-size:13.5px}
.badge{position:absolute;top:15px;right:15px;font-size:10.5px;font-weight:700;letter-spacing:.05em;padding:3px 9px;border-radius:999px;background:rgba(245,158,11,.16);color:#f59e0b}
.card .run{margin-top:12px;color:#7f9cff;font-size:13px;font-weight:600}
.ov{position:fixed;inset:0;background:rgba(4,6,14,.74);display:none;align-items:flex-start;justify-content:center;padding:38px 16px;overflow:auto;z-index:50}
.ov.on{display:flex}
.modal{background:#0f1526;border:1px solid #263154;border-radius:18px;max-width:720px;width:100%;padding:26px 28px}
.x{float:right;color:#7f8fb3;cursor:pointer;font-size:20px;line-height:1;user-select:none}
.modal h2{font-size:20px;margin-bottom:6px;padding-right:24px}
.situation{background:#0b1226;border:1px solid #263154;border-radius:10px;padding:13px 15px;color:#cdd8f0;font-size:14px;margin:14px 0 18px}
.controls{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.lbl{color:#7f8fb3;font-size:12.5px;margin-right:2px}
.seg{display:inline-flex;background:#0b1226;border:1px solid #263154;border-radius:10px;overflow:hidden}
.seg button{background:none;border:none;color:#93a4c8;padding:9px 14px;font:inherit;font-size:13px;cursor:pointer}
.seg button.on{background:#1c2a4d;color:#fff;font-weight:600}
.go{background:#f26a1b;border:none;color:#fff;font-weight:700;font-size:15px;padding:11px 22px;border-radius:10px;cursor:pointer;margin-top:16px}
.go:disabled{opacity:.5;cursor:default}
.muted{color:#7f8fb3;font-size:12.5px}
.steps{margin-top:22px}
.step{display:flex;align-items:center;gap:11px;padding:7px 0;color:#7f8fb3;font-size:14px;opacity:.4;transition:.3s}
.step.on{opacity:1;color:#e7ecf5}.step.done{opacity:1;color:#7ee2ad}
.step .m{width:20px;height:20px;border-radius:50%;border:2px solid #2c3a5e;display:grid;place-items:center;flex:none;font-size:11px}
.step.on .m{border-color:#f26a1b;border-top-color:transparent;animation:spin .7s linear infinite}
.step.done .m{border-color:#22c55e;background:rgba(34,197,94,.16);color:#22c55e}
@keyframes spin{to{transform:rotate(360deg)}}
.verdict{border-radius:12px;padding:14px 16px;margin-top:20px;font-weight:600;font-size:15px}
.verdict.win{background:rgba(34,197,94,.12);border:1px solid rgba(34,197,94,.4);color:#7ee2ad}
.verdict.lose{background:rgba(229,72,77,.12);border:1px solid rgba(229,72,77,.4);color:#ff9ea1}
.rescard{background:#0b1226;border:1px solid #263154;border-radius:10px;padding:13px 16px;margin-top:11px}
.rescard .k{color:#7f8fb3;font-size:11.5px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:5px}
.rescard .v{font-size:15px}
.foot{margin-top:15px;color:#7f8fb3;font-size:12.5px}
.links{margin-top:34px;display:flex;gap:18px;flex-wrap:wrap}
.links a{color:#7f9cff;font-size:13px;text-decoration:none}.links a:hover{text-decoration:underline}
</style></head><body>
<div class="wrap">
  <header><h1>CMO Copilot</h1><span class="dot" id="status" data-live=""><i></i>…</span></header>
  <p class="sub">An AI copilot for marketing-budget decisions. Pick a real situation, then watch a
    <b>single model</b> guess at it — and watch a <b>6-agent society</b> reason it out. Runs are
    <b>free &amp; instant</b> by default; flip to <b>Live on Qwen</b> to call Alibaba Cloud Model Studio for real.</p>
  <a href="/submission" style="display:inline-block;margin:0 0 26px;background:#f26a1b;color:#fff;font-weight:700;padding:11px 20px;border-radius:10px;text-decoration:none">📄 Read the full hackathon submission →</a>
  <div class="grid" id="grid"></div>
  <div class="links">
    <a href="/api/health">/api/health</a><a href="/docs">API explorer</a>
    <a href="https://github.com/vidiyala84/cmo-copilot">Source &amp; write-up ↗</a>
  </div>
</div>
<div class="ov" id="ov"><div class="modal" id="modal"></div></div>
<script>
const ACT={shift_budget:"Shift budget between campaigns",increase_budget:"Increase the budget",decrease_budget:"Cut the budget",refresh_creative:"Refresh the creative",fix_targeting:"Fix the targeting",launch_campaign:"Launch a new campaign",fix_tracking:"Fix tracking — the data is broken",no_action:"Hold — do nothing"};
const ROOT={creative_fatigue:"Creative fatigue — the ad wore out",tracking_outage:"Tracking outage — measurement broke",seasonality:"Seasonality — a market-wide dip",audience_saturation:"Audience saturation",competitor_pressure:"Competitor pressure",winner_opportunity:"A winner worth scaling",brand_demand_dip:"Brand demand dip",learning_phase:"Learning phase — too soon to judge",budget_cap:"Held back by a budget cap",emerging_segment:"An emerging segment",noise:"Just noise — nothing real"};
const TOOL={get_campaign_metrics:"Pulled the campaign metrics",get_group_campaigns:"Drilled into a campaign group",diagnose_drivers:"Diagnosed what changed",find_opportunities:"Scanned for opportunities",recommend_portfolio:"Assembled a portfolio plan",forecast_impact:"Forecast the impact",forecast_roas:"Forecast the ROAS impact",propose_reallocation:"Checked it against the guardrails"};
const hz=(m,k)=>m[k]||k;
let SCEN=[];
fetch('/api/health').then(r=>r.json()).then(h=>{const el=document.getElementById('status');
  el.dataset.live=h.live_available?'1':'';
  el.innerHTML='<i style="background:'+(h.live_available?'#22c55e':'#f59e0b')+'"></i>'+(h.live_available?'live · Qwen on Model Studio':'instant mode');}).catch(()=>{});
fetch('/api/scenarios').then(r=>r.json()).then(d=>{SCEN=Array.isArray(d)?d:[];
  document.getElementById('grid').innerHTML=SCEN.map((s,i)=>'<div class="card" onclick="openRun('+i+')">'+
    (s.is_trap?'<span class="badge">TRAP</span>':'')+'<h3>'+s.name+'</h3><p>'+(s.perturb||'')+'</p>'+
    '<div class="run">▶ Run this decision</div></div>').join('');});
const ov=document.getElementById('ov'),modal=document.getElementById('modal');
ov.onclick=e=>{if(e.target===ov)closeM()};
addEventListener('keydown',e=>{if(e.key==='Escape')closeM()});
function closeM(){ov.classList.remove('on')}
let cur={i:0,approach:'society',live:false};
function openRun(i){cur={i,approach:'society',live:false};const s=SCEN[i];
  modal.innerHTML='<span class="x" onclick="closeM()">✕</span><h2>'+s.name+'</h2>'+
    '<div class="situation"><b>The situation:</b> '+(s.perturb||'')+'</div>'+
    '<div class="controls"><span class="lbl">Approach</span>'+
      '<div class="seg" id="appr"><button data-a="direct" onclick="setA(\'direct\')">Single model</button>'+
      '<button data-a="society" class="on" onclick="setA(\'society\')">Agent society (6)</button></div>'+
      '<div class="seg" id="mode"><button data-m="0" class="on" onclick="setM(0)">Instant · free</button>'+
      '<button data-m="1" onclick="setM(1)">Live Qwen ⚡</button></div></div>'+
    '<button class="go" id="go" onclick="runIt()">▶ Run it</button>'+
    '<span class="muted" id="hint" style="margin-left:12px"></span><div id="out"></div>';
  ov.classList.add('on');updHint();}
function setA(a){cur.approach=a;document.querySelectorAll('#appr button').forEach(b=>b.classList.toggle('on',b.dataset.a===a));}
function setM(m){cur.live=!!m;document.querySelectorAll('#mode button').forEach(b=>b.classList.toggle('on',b.dataset.m===String(m)));updHint();}
function updHint(){const live=document.getElementById('status').dataset.live,h=document.getElementById('hint');
  h.textContent=(cur.live&&!live)?'No key on this server — will run instant instead.':cur.live?'Calls real Qwen — a few seconds, uses tokens.':'Deterministic, no tokens.';}
const STEPS={direct:["Reading the dashboard numbers…","Thinking it over…","Answering"],
  society:["Analyst reads the account…","Forecaster projects the impact…","Risk Officer checks for traps…","The team rules on a decision…"]};
async function runIt(){const go=document.getElementById('go');go.disabled=true;const out=document.getElementById('out');
  const labels=STEPS[cur.approach];
  out.innerHTML='<div class="steps">'+labels.map((l,i)=>'<div class="step" id="st'+i+'"><span class="m"></span>'+l+'</div>').join('')+'</div>';
  let si=0;const adv=()=>{if(si>0){const p=document.getElementById('st'+(si-1));if(p)p.className='step done';}const e=document.getElementById('st'+si);if(e)e.className='step on';si++;};
  adv();const timer=setInterval(()=>{if(si<labels.length)adv();},700);const t0=Date.now();let res;
  try{res=await fetch('/api/live/run',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({scenario:SCEN[cur.i].id,approach:cur.approach,mock:!cur.live})}).then(r=>r.json());}
  catch(err){clearInterval(timer);out.innerHTML='<div class="verdict lose">Something went wrong. Try again.</div>';go.disabled=false;return;}
  const wait=Math.max(0,2000-(Date.now()-t0));
  setTimeout(()=>{clearInterval(timer);labels.forEach((_,i)=>{const e=document.getElementById('st'+i);if(e)e.className='step done';});render(res);go.disabled=false;},wait);}
function render(r){const out=document.getElementById('out');
  if(!r||!r.decision){out.querySelector('.steps').insertAdjacentHTML('afterend','<div class="verdict lose">The run returned no decision.</div>');return;}
  const d=r.decision,ex=r.expected||{},correct=d.action===ex.action,trap=r.is_trap;
  const v=correct?'<div class="verdict win">✓ Correct — it matched the expert answer'+(trap?', and avoided the trap.':'.')+'</div>'
    :'<div class="verdict lose">✗ Missed it'+(trap?' — this was a trap, and the obvious move was wrong.':'.')+'</div>';
  const tools=(r.tool_log||[]).map(e=>hz(TOOL,e.tool));
  const toolsHtml=tools.length?'<div class="rescard"><div class="k">How it worked — steps it took</div><div class="v">'+tools.map(t=>'• '+t).join('<br>')+'</div></div>':'';
  const ruling=(r.transcript&&r.transcript.ruling_reason)?'<div class="rescard"><div class="k">The team’s ruling</div><div class="v">'+r.transcript.ruling_reason+'</div></div>':'';
  const foot=cur.live?('Live Qwen · '+(r.tokens||0)+' tokens · '+r.latency_s+'s'):'Instant mode · deterministic';
  out.querySelector('.steps').insertAdjacentHTML('afterend',v+
    '<div class="rescard"><div class="k">Its diagnosis</div><div class="v">'+hz(ROOT,d.root_cause)+'</div></div>'+
    '<div class="rescard"><div class="k">Its recommendation</div><div class="v"><b>'+hz(ACT,d.action)+'</b>'+(d.rationale?'<br><span class="muted">'+d.rationale+'</span>':'')+'</div></div>'+
    toolsHtml+ruling+
    '<div class="rescard"><div class="k">The expert answer</div><div class="v">'+hz(ROOT,ex.root_cause)+' → <b>'+hz(ACT,ex.action)+'</b></div></div>'+
    '<div class="foot">'+foot+'</div>');}
</script></body></html>"""


SUBMISSION_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CMO Copilot — Hackathon submission</title>
<style>
:root{color-scheme:dark}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#0b1020;color:#dbe3f2;line-height:1.62}
.wrap{max-width:820px;margin:0 auto;padding:40px 22px 90px}
a{color:#7f9cff}
.back{font-size:14px;color:#7f9cff;text-decoration:none}
.eyebrow{color:#FF8431;font-weight:800;font-size:13px;letter-spacing:.16em;text-transform:uppercase;margin:20px 0 10px}
h1{font-size:38px;letter-spacing:-.02em;color:#fff}
.pitch{font-size:19px;color:#aebbd6;margin:14px 0 8px}
.note{background:#141b30;border:1px solid #2a3557;border-left:3px solid #f26a1b;border-radius:8px;padding:12px 16px;margin:22px 0;font-size:14.5px;color:#c7d3ee}
h2{font-size:23px;color:#fff;margin:38px 0 12px;letter-spacing:-.01em}
p{margin:12px 0}
b,strong{color:#fff}
ul{margin:12px 0 12px 22px}li{margin:7px 0}
table{width:100%;border-collapse:collapse;margin:18px 0;font-size:14px}
th,td{padding:9px 10px;text-align:center;border-bottom:1px solid #263154}
th{color:#93a4c8;font-size:12px;text-transform:uppercase;letter-spacing:.04em}
td:first-child,th:first-child{text-align:left}
tr.win td{color:#7ee2ad;font-weight:700}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}
.chip{background:#141b30;border:1px solid #2a3557;color:#c7d3ee;border-radius:999px;padding:5px 12px;font-size:13px}
.grid2{display:grid;grid-template-columns:180px 1fr;gap:10px 18px;margin:14px 0;font-size:14.5px}
.grid2 .k{color:#8595bb}
pre{background:#0e1526;border:1px solid #263154;border-radius:10px;padding:16px;overflow-x:auto;font-size:13px;color:#c7d3ee;margin:14px 0}
code{font-family:ui-monospace,Menlo,monospace}
.links a{display:inline-block;margin:6px 16px 6px 0}
hr{border:0;border-top:1px solid #263154;margin:34px 0}
</style></head><body>
<div class="wrap">
  <a class="back" href="/">← back to the live demo</a>
  <div class="eyebrow">Qwen Cloud Hackathon · Submission</div>
  <h1>CMO Copilot</h1>
  <p class="pitch">An AI copilot for marketing budgets: a 6-agent Qwen society whose own mistakes a
    memory learns to override — reliable enough to know when the right move is to do nothing.</p>
  <div class="note">This page is the deployed app's full write-up — everything the hackathon entry
    form would contain. The site you came from (<a href="/">/</a>) is the live, interactive demo; it
    runs on <b>Qwen via Alibaba Cloud Model Studio</b>.</div>

  <h2>💡 Inspiration</h2>
  <p>Every week a marketing leader faces the same question: <b>"ROAS moved — what do I do with the
    budget?"</b> And the intuitive answer is usually <i>wrong</i>. Conversions crashed? It might be a
    broken tracking pixel, not a real drop — moving budget makes it worse. Everything down at once?
    Probably seasonality — hold. The worst performer is the brand campaign? Don't touch it. I didn't
    want a demo that looks smart on the happy path — I wanted to find what it takes to make an agent
    <b>reliable</b> on decisions where the obvious move is a trap, so I built a controlled experiment.</p>

  <h2>🎯 What it does</h2>
  <p><b>CMO Copilot</b> turns a fuzzy CMO question into a reliable, auditable recommendation over a
    real ad account (~300 campaigns, $1.2M/month):</p>
  <ul>
    <li>A <b>6-agent Qwen society</b> — Analyst, Forecaster, Risk Officer, Portfolio Planner, Growth
      Lead, Coordinator — diagnoses the account, debates under a structured protocol, vetoes a bad
      move, or assembles a multi-item plan.</li>
    <li>A <b>memory that learns which of the society's own calls to override</b> — from experience,
      not rules I typed in. When a decision backfires it learns a <i>structured gate</i> from the
      outcome, keeps only the gates its own history proves <b>matter</b>, and enforces them
      deterministically.</li>
  </ul>
  <p>Everything is measured on a <b>100-question benchmark</b> generated with deterministic Python —
    no model in the generation — where every correct answer is <i>proven present in the data</i>
    before it counts. <b>The result: 27% → 100% on the same benchmark, and it holds.</b></p>

  <h2>🧪 The experiment — and the honest result</h2>
  <p>Seven architectures, the identical 100 questions, live on Qwen Cloud:</p>
  <table><thead><tr><th>Approach</th><th>Overall</th><th>Simple</th><th>Traps</th><th>Plans</th></tr></thead><tbody>
    <tr><td>Just ask Qwen</td><td>27%</td><td>2%</td><td>65%</td><td>0%</td></tr>
    <tr><td>+ every rule in the prompt</td><td>51%</td><td>36%</td><td>91%</td><td>0%</td></tr>
    <tr><td>Single agent + tools</td><td>57%</td><td>80%</td><td>48%</td><td>27%</td></tr>
    <tr><td>6-agent society</td><td>66%</td><td>80%</td><td>86%</td><td>100%</td></tr>
    <tr><td>LLM planner</td><td>71%</td><td>95%</td><td>32%</td><td>100%</td></tr>
    <tr><td>Tool-derived (structured)</td><td>76%</td><td>100%</td><td>40%</td><td>100%</td></tr>
    <tr class="win"><td>Compose → gated planner</td><td>100%</td><td>100%</td><td>100%</td><td>100%</td></tr>
  </tbody></table>
  <p><b>No single approach wins all three tiers, and the failure modes are opposite.</b> Rules and the
    veto crack the <b>traps</b> (when to <i>hold</i>). Tools and planning crack the <b>fixes and plans</b>
    (what to <i>do</i>). Compose them — a planner behind a risk/trap gate — and it solves everything.
    But that <b>hand-codes</b> the gates, which raised the real question: <i>can a memory <b>learn</b>
    them?</i></p>

  <h2>🏗️ How I built it</h2>
  <ul>
    <li><b>Qwen on Alibaba Cloud Model Studio</b>, used deliberately: <code>qwen-plus</code> for
      orchestration, <code>qwen-flash</code> for cheap sub-tasks, <code>qwen-max</code> for synthesis,
      via an OpenAI-compatible tool-calling loop, with <code>text-embedding-v3</code> powering memory retrieval.</li>
    <li>A <b>Model Context Protocol (MCP) server</b> exposing the whole tool belt — so any MCP client
      can diagnose and plan against the account with audited, group-rollup, O(1)-context tools.</li>
    <li><b>The learned memory</b>: it observes raw features (funnel drops, elasticity, ROAS spread,
      flags, opportunity lift) and fits a <b>decision tree</b> on its accumulated outcome history each
      session. The tree discovers the thresholds itself — e.g. <code>cvr_drop &gt; 0.53 → fix_tracking</code>.
      A gate fires only if history shows it <i>mattered</i> (the base was really getting those cases
      wrong), and enforcement is a deterministic match — not an LLM re-reading its own note.</li>
    <li><b>Engineering</b>: ~300 campaigns rolled up to 5 groups for O(1) context (dumping the account
      blows the 32k window past ~500 campaigns), a deterministic offline mode for reproducible CI,
      fail-closed constraints, and <b>170 automated tests</b>.</li>
  </ul>

  <h2>🧗 Challenges &amp; honest negatives</h2>
  <ul>
    <li><b>The obvious memory doesn't work.</b> Prose memory (the model writing itself lessons)
      discovers the right gates but <i>oscillates and degrades</i> (30→44→46→32→31% on the traps over
      5 sessions). Outcome-based feedback was steadier but still didn't converge. I report both
      negatives in full.</li>
    <li><b>Overfitting.</b> My first "structured gate" hand-set the thresholds. I caught it — that's
      <i>me</i> learning, not the memory — and replaced it with a decision tree that learns the boundaries.</li>
    <li><b>The hold-vs-plan tension is real</b> and had to be composed, not chosen.</li>
  </ul>

  <h2>🏆 Accomplishments &amp; what I learned</h2>
  <p>A memory that <b>learns and stays stable</b>: Society + Memory <b>74% → 100% over four sessions,
    and it holds</b> — where every prose variant oscillated. The tree learned on a live Qwen base is
    <i>identical</i> to the one on a deterministic base, because it learns the task's structure, not
    the base's noise — and enforcement costs <b>zero</b> LLM calls, so it gets cheaper as it learns.
    A smart model is table stakes; reliability comes from a specialist society that reasons and a
    memory that learns from experience which of its calls to override.</p>

  <hr>
  <h2>Built with</h2>
  <div class="chips">
    <span class="chip">qwen</span><span class="chip">alibaba-cloud</span><span class="chip">model-studio</span>
    <span class="chip">dashscope</span><span class="chip">mcp</span><span class="chip">fastmcp</span>
    <span class="chip">python</span><span class="chip">scikit-learn</span><span class="chip">decision-trees</span>
    <span class="chip">embeddings</span><span class="chip">fastapi</span><span class="chip">docker</span>
  </div>

  <h2>Details</h2>
  <div class="grid2">
    <span class="k">Submitter</span><span>Individual — Sravan Vidiyala</span>
    <span class="k">Track</span><span>MemoryAgent (learned-gate memory is the centerpiece)</span>
    <span class="k">Newly built</span><span>Yes — original to this hackathon</span>
    <span class="k">Model</span><span>Qwen on Alibaba Cloud Model Studio (qwen-plus / qwen-flash / qwen-max · text-embedding-v3)</span>
    <span class="k">Deployment</span><span>This service, on Alibaba Cloud ECS (Docker)</span>
    <span class="k">AI-service usage</span><span><a href="https://github.com/vidiyala84/cmo-copilot/blob/main/cmo/config.py">cmo/config.py</a> (Model Studio endpoint) · <a href="https://github.com/vidiyala84/cmo-copilot/blob/main/cmo/llm.py">cmo/llm.py</a> (the Qwen client)</span>
  </div>

  <h2>Links</h2>
  <div class="links">
    <a href="/">▶ Live interactive demo (this deployment)</a>
    <a href="https://youtu.be/00gOMfxoiv0">🎬 3-min demo video</a>
    <a href="https://github.com/vidiyala84/cmo-copilot">Code &amp; write-up (GitHub, MIT)</a>
    <a href="/api/health">/api/health</a>
    <a href="/docs">API explorer</a>
  </div>

  <h2>Testing instructions</h2>
  <p>No credentials required — everything runs offline, deterministically:</p>
  <pre><code>pip install -r requirements.txt
pytest -q                                              # 170 tests, all pass
python -m cmo.harness --agent mock                     # offline canary
python -m cmo.benchmark --mock                         # the 100-question benchmark
python -m tracks.track1.memory_gates --sessions 4 --base society   # Society + learned Memory -> 100%
python -m cmo.build_review                             # -> benchmark_review.html (all 100, reviewable)
python -m cmo.mcp_server                               # the MCP server (stdio)</code></pre>
  <p>For the live Qwen Cloud numbers, put <code>DASHSCOPE_API_KEY</code> in <code>.env</code>, then
    <code>python scripts/check_live.py &amp;&amp; python -m cmo.bench_live</code>.</p>

  <p style="margin-top:34px"><a class="back" href="/">← back to the live demo</a></p>
</div>
</body></html>"""


# --------------------------------------------------------------------- routes

@app.get("/", response_class=HTMLResponse)
def root():
    return INDEX_HTML


@app.get("/submission", response_class=HTMLResponse)
def submission():
    return SUBMISSION_HTML


@app.get("/api/health")
def health():
    return {"ok": True, "provider": LLM_PROVIDER, "models": MODELS,
            "live_available": bool(QWEN_API_KEY)}


@app.get("/api/scenarios")
def scenarios():
    return [{"id": s["id"], "name": s["name"], "expected": s["expected"],
             "is_trap": s["id"] in TRAPS, "perturb": PERTURB.get(s["id"], "")}
            for s in SCENARIOS]


PERTURB = {
    "S01": "C1 'Summer Sale' click-through rate decays ~40% over the last 14 days (ad fatigue). Clicks & conversions fall together.",
    "S02": "C1 conversions/revenue collapse to ~15% while CLICKS stay normal — a tracking-pixel outage disguised as a performance drop.",
    "S03": "Every campaign's conversions/revenue drop ~25% together — a market-wide seasonal dip.",
    "S04": "C3 'Retargeting' conversion rate decays ~35% (audience saturated); clicks unaffected.",
    "S05": "C4 'Generic Search' clicks/conversions drop ~30% — a competitor bidding up the auction (CPC up).",
    "S06": "C5 'Advantage+' conversions climb ~35% — a winner you should feed.",
    "S07": "C2 'Brand Search' (the protected brand campaign) is the worst performer — but it's an external demand dip. TRAP: don't cut brand.",
    "S08": "C1 was rebuilt 3 days ago; its numbers are noisy/down. TRAP: it's in the learning phase — be patient, don't touch it.",
    "S09": "C5 is winning AND flagged losing 45% impression share to budget caps. TRAP: increase its budget, don't just shift it.",
    "S10": "Nothing meaningful happened — all movements are within normal variance.",
}


@app.get("/api/data")
def data():
    from cmo.config import CONSTRAINTS, GROUPS, N_DAYS, WINDOW, SEED
    from cmo.portfolio import portfolio_summary
    from cmo.tools import OPENAI_TOOL_SPECS, BENCHMARKS
    # The 5 decision units. Each rolls up `n_campaigns` live campaigns.
    campaigns = [{"id": g["id"], "name": g["name"], "platform": g["platform"], "kind": g["kind"],
                  "daily_spend": g["daily_spend"], "ctr": g["ctr"], "cvr": g["cvr"], "aov": g["aov"],
                  "n_campaigns": g["n_campaigns"]} for g in GROUPS]
    tools = [{"name": f["function"]["name"], "description": f["function"]["description"]}
             for f in OPENAI_TOOL_SPECS]
    tools += [{"name": "apply_reallocation", "description": "Sandbox execution — writes a run manifest to the ledger. (Track 4 only; not exposed to the diagnosing agents.)"},
              {"name": "send_approval_request", "description": "Human approval gate stub. (Track 4 only.)"}]
    scen = [{"id": s["id"], "name": s["name"], "expected": s["expected"],
             "is_trap": s["id"] in TRAPS, "perturb": PERTURB.get(s["id"], "")} for s in SCENARIOS]
    sample = generate_base()[:10]
    return {"campaigns": campaigns, "constraints": CONSTRAINTS, "benchmarks": BENCHMARKS,
            "tools": tools, "scenarios": scen, "sample_rows": sample,
            "sim": {"days": N_DAYS, "recent_window": WINDOW, "seed": SEED,
                    "n_groups": len(campaigns), **portfolio_summary()},
            "models": MODELS}


@app.get("/api/baseline")
def baseline(live: bool = False):
    if live:
        from cmo.agents import QwenBaselineAgent
        agent = QwenBaselineAgent()
    else:
        from cmo.agents import MockHeuristicAgent
        agent = MockHeuristicAgent()
    results = harness_run(agent)
    return {"agent": agent.name, "mode": "live" if live else "mock",
            "total": round(sum(r["score"] for r in results), 2),
            "results": _results_payload(results)}


@app.get("/api/overview")
def overview(refresh: bool = False):
    if not refresh and "overview" in _cache:
        return _cache["overview"]

    from cmo.agents import MockHeuristicAgent
    from tracks.track3.society import SocietyAgent
    from tracks.track1.session_runner import run_sessions
    from tracks.track4.autopilot import Autopilot

    base = harness_run(MockHeuristicAgent())
    base_total = round(sum(r["score"] for r in base), 2)

    society = harness_run(SocietyAgent(mock=True, transcripts_dir=UI_RUNS / "transcripts"))
    soc_total = round(sum(r["score"] for r in society), 2)

    mem = run_sessions(sessions=5, mock=True, db_path=str(UI_RUNS / "memory.db"))

    auto = Autopilot(mock=True, auto_approve=True, out_dir=UI_RUNS).run_all()
    exp = {s["id"]: s["expected"] for s in SCENARIOS}
    auto_score = round(sum(score(r.decision, exp[r.scenario])[0] if r.decision else 0
                           for r in auto), 2)

    payload = {
        "provider": LLM_PROVIDER, "models": MODELS,
        "baseline": {"total": base_total,
                     "per_scenario": {r["scenario"]: r["score"] for r in base}},
        "society": {"total": soc_total,
                    "per_scenario": {r["scenario"]: r["score"] for r in society}},
        "memory": {"curve": mem["curve"], "baseline": mem["baseline_total"],
                   "gain": mem["gain"], "sessions": mem["sessions"]},
        "autopilot": {"score": auto_score,
                      "safe": sum(r.safe for r in auto),
                      "executed": sum(r.executed for r in auto),
                      "rolled_back": sum(r.rolled_back for r in auto),
                      "n": len(auto)},
        "traps": sorted(TRAPS),
    }
    _cache["overview"] = payload
    return payload


@app.get("/api/live/benchmark")
def live_benchmark():
    """Serve the precomputed LIVE benchmark (direct / baseline / society / memory),
    all real Qwen on Qwen Cloud (Model Studio). Assembled by bench_live.py."""
    import json as _json
    path = RUNS_DIR / "live_benchmark.json"
    if not path.exists():
        return {"ready": False}
    data = _json.loads(path.read_text())
    data["ready"] = True
    # merge in the Memory+Society combo if it's been run
    ms = RUNS_DIR / "memory_society_live.json"
    if ms.exists():
        m = _json.loads(ms.read_text())
        data["memsoc"] = {"curve": m["curve"], "baseline": m["baseline_total"],
                          "gain": m["gain"], "per_session": m["per_session"]}
    # merge in "Direct Qwen + rules" if it's been run
    dr = RUNS_DIR / "direct_rules_live.json"
    if dr.exists():
        data["direct_rules"] = _json.loads(dr.read_text())
    return data


@app.get("/api/questions")
def questions_bench():
    import json as _json
    path = RUNS_DIR / "questions_live.json"
    if not path.exists():
        return {"ready": False}
    d = _json.loads(path.read_text())
    d["ready"] = True
    return d


@app.get("/api/scaling")
def scaling():
    import json as _json
    path = RUNS_DIR / "scaling.json"
    if not path.exists():
        return {"ready": False}
    d = _json.loads(path.read_text())
    d["ready"] = True
    return d


@app.get("/api/live/memsoc")
def live_memsoc():
    """Cached LIVE Memory+Society 5-session run (full report shape)."""
    import json as _json
    path = RUNS_DIR / "memory_society_live.json"
    if not path.exists():
        return {"ready": False}
    data = _json.loads(path.read_text())
    data["ready"] = True
    return data


@app.post("/api/live/run")
def live_run(req: LiveRunReq):
    """Run ONE scenario live on real Qwen with the chosen approach."""
    import time
    sc = _scenario(req.scenario)
    env = ScenarioEnv(generate_base(), sc)
    t0 = time.time()
    transcript = None
    if req.approach == "baseline":
        from cmo.agents import QwenBaselineAgent
        from cmo.llm import MockLLM
        agent = QwenBaselineAgent(llm=MockLLM() if req.mock else None)
        decision = agent.decide(env)
        tokens = agent.llm.usage().get("total_tokens", 0)
    elif req.approach == "society":
        from tracks.track3.society import SocietyAgent
        agent = SocietyAgent(mock=req.mock, transcripts_dir=UI_RUNS / "transcripts")
        decision = agent.decide(env)
        transcript = agent.last_transcript
        tokens = (transcript or {}).get("total_tokens", 0)
    elif req.approach == "direct_rules":
        from cmo.agents import DirectQwenAgent
        agent = DirectQwenAgent(mock=req.mock, with_rules=True)
        decision = agent.decide(env)
        tokens = agent.last_tokens.get("total_tokens", 0)
    else:  # direct
        from cmo.agents import DirectQwenAgent
        agent = DirectQwenAgent(mock=req.mock)
        decision = agent.decide(env)
        tokens = agent.last_tokens.get("total_tokens", 0)
    s, notes = score(decision, sc["expected"])
    return {"scenario": req.scenario, "name": sc["name"], "approach": req.approach,
            "decision": decision, "score": s, "notes": notes, "expected": sc["expected"],
            "is_trap": req.scenario in TRAPS, "tokens": tokens,
            "latency_s": round(time.time() - t0, 2), "transcript": transcript,
            "tool_log": [{"tool": e["tool"], "args": e.get("args", {})} for e in env.tool_log]}


@app.get("/api/live/memory")
def live_memory():
    """Cached LIVE 5-session memory run (full report shape)."""
    import json as _json
    path = RUNS_DIR / "memory_live.json"
    if not path.exists():
        return {"ready": False}
    data = _json.loads(path.read_text())
    data["ready"] = True
    return data


@app.post("/api/track1/run")
def track1_run(req: Track1Req):
    from tracks.track1.session_runner import run_sessions
    return run_sessions(sessions=max(1, min(req.sessions, 10)), mock=not req.live,
                        db_path=str(UI_RUNS / "memory.db"))


@app.get("/api/track3/all")
def track3_all():
    from tracks.track3.society import SocietyAgent
    agent = SocietyAgent(mock=True, transcripts_dir=UI_RUNS / "transcripts")
    base = generate_base()
    out = []
    for sc in SCENARIOS:
        env = ScenarioEnv(base, sc)
        decision = agent.decide(env)
        s, _ = score(decision, sc["expected"])
        t = agent.last_transcript
        out.append({"scenario": sc["id"], "name": sc["name"], "score": s,
                    "decision": decision, "expected": sc["expected"],
                    "is_trap": sc["id"] in TRAPS,
                    "conflicts_resolved": t["conflicts_resolved"],
                    "ruling_reason": t["ruling_reason"], "rounds": t["rounds"]})
    return {"total": round(sum(o["score"] for o in out), 2), "results": out}


@app.get("/api/track3/{sid}")
def track3_one(sid: str, live: bool = False, fresh: bool = False):
    import json as _json
    sc = _scenario(sid)
    # live + not forced fresh -> serve the cached LIVE transcript (instant, no re-spend)
    if live and not fresh:
        p = RUNS_DIR / "transcripts_live" / f"{sid}.json"
        if p.exists():
            t = _json.loads(p.read_text())
            decision = t["final_decision"]
            s, notes = score(decision, sc["expected"])
            return {"scenario": sid, "name": sc["name"], "score": s, "notes": notes,
                    "decision": decision, "expected": sc["expected"], "transcript": t,
                    "tool_log": [], "cached_live": True}
    from tracks.track3.society import SocietyAgent
    agent = SocietyAgent(mock=not live, transcripts_dir=UI_RUNS / "transcripts")
    env = ScenarioEnv(generate_base(), sc)
    decision = agent.decide(env)
    s, notes = score(decision, sc["expected"])
    return {"scenario": sid, "name": sc["name"], "score": s, "notes": notes,
            "decision": decision, "expected": sc["expected"],
            "transcript": agent.last_transcript,
            "tool_log": [{"tool": e["tool"], "args": e.get("args", {})} for e in env.tool_log]}


@app.post("/api/track4/run")
def track4_run(req: Track4Req):
    from tracks.track4.autopilot import Autopilot
    from tracks.track4.alerts import all_alerts

    responders = {
        "approve": lambda rq, t: "approve",
        "reject": lambda rq, t: "reject demo: not this week",
        "adjust": lambda rq, t: "adjust 10",
        "expire": lambda rq, t: None,
    }
    auto_approve = req.gate == "auto"
    responder = None if auto_approve else responders.get(req.gate, responders["approve"])

    pilot = Autopilot(mock=not req.live, auto_approve=auto_approve, inject_fault=req.fault,
                      out_dir=UI_RUNS, responder=responder)
    alert = next(a for a in all_alerts() if a.scenario_id == req.scenario)
    res = pilot.run_one(alert)
    sc = _scenario(req.scenario)
    payload = res.to_dict()
    payload["mode"] = "live" if req.live else "mock"
    payload["expected"] = sc["expected"]
    payload["scenario_name"] = sc["name"]
    payload["alert"] = alert.text
    payload["ground_truth"] = sc["name"]
    payload["score"] = score(res.decision, sc["expected"])[0] if res.decision else None
    diag = getattr(pilot.diagnose_agent, "last_transcript", None)
    if diag:
        payload["diagnosis_tokens"] = diag.get("total_tokens", 0)
        payload["diagnosis_latency_s"] = diag.get("latency_s")
    return payload
