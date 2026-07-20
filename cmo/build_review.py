"""Render all 100 benchmark questions to a self-contained HTML review page.

Written for a business reviewer (e.g. a Head of Marketing): each card tells the
story of what is happening in the ad account that week, shows the evidence an
agent would see, and explains the recommended action and why — including why the
traps are traps. Nothing here calls a model; it is the same deterministic data
the benchmark scores against.

    python build_review.py   ->   benchmark_review.html
"""
import html
from pathlib import Path

from cmo.benchmark import generate, validate
from cmo.datagen import generate_base
from cmo.portfolio import GROUP_IDS, GROUP_META
from cmo.scenarios import EMERGING_SEGMENT
from cmo.tools import ScenarioEnv


def gname(gid):
    if not gid:
        return "a NEW campaign"
    m = GROUP_META[gid]
    return f"{m['name']} ({m['platform']})"


def _pct(v):
    return "—" if v is None else f"{v:+.0f}%"


def _evidence(env):
    metrics = env.get_campaign_metrics()
    rows = []
    for gid in GROUP_IDS:
        dd = env.diagnose_drivers(gid)
        d = dd["drivers"]
        flags = env.meta.get(gid, {})
        flag_txt = ", ".join(f"{k}={v}" for k, v in flags.items()) if flags else ""
        roas, ctr, cvr = metrics[gid]["roas_change_pct"], d["creative"]["change_pct"], d["targeting"]["change_pct"]
        moved = (roas is not None and abs(roas) >= 8) or bool(flags) or abs(ctr) >= 12 or abs(cvr) >= 12
        rows.append({"gid": gid, "name": GROUP_META[gid]["name"], "platform": GROUP_META[gid]["platform"],
                     "roas": roas, "ctr": ctr, "cvr": cvr, "b": d["budget"]["ratio"],
                     "flags": flag_txt, "moved": moved})
    opps = [o for o in env.find_opportunities()["opportunities"] if o["segment"] == EMERGING_SEGMENT]
    return rows, opps, metrics


def _moved(rows):
    cand = [r for r in rows if r["moved"]]
    return max(cand, key=lambda r: abs(r["roas"] or 0)) if cand else None


# --------------------------------------------------------------------------
# Business narratives — "what's happening" + "what to do and why", per type.
# Returns (situation_html, recommendation_html).
# --------------------------------------------------------------------------

def _narrative(sc, rows, opps):
    root = sc["expected"]["root_cause"]
    g = _moved(rows)
    gn = gname(g["gid"]) if g else "the account"

    if root == "creative_fatigue":
        sit = (f"The <b>{gn}</b> campaign is still being served as much as before, but people have "
               f"stopped clicking — its click-through rate dropped <b>{_pct(g['ctr'])}</b>, dragging "
               f"return on ad spend down <b>{_pct(g['roas'])}</b>. The audience has seen this ad too "
               f"many times and tuned it out. This is classic <b>creative fatigue</b>.")
        rec = ("Refresh the creative — new images/copy. The demand is still there; the ad went stale. "
               "Moving budget away would be a mistake: a tired ad doesn't get better with less money, "
               "and this campaign can still perform with a fresh execution.")
    elif root == "audience_saturation":
        sit = (f"People still click <b>{gn}</b>'s ads at the normal rate, but far fewer of those clicks "
               f"turn into sales — conversion rate fell <b>{_pct(g['cvr'])}</b> while click-through held "
               f"flat. ROAS is down <b>{_pct(g['roas'])}</b>. The ad is doing its job earning attention; "
               f"the problem is who we're reaching — the best prospects are exhausted.")
        rec = ("Fix the targeting — tighten or refresh the audience. Adding budget here would just buy "
               "more low-quality clicks that don't convert. The lever is audience, not spend.")
    elif root == "emerging_segment":
        o = opps[0] if opps else {"segment": EMERGING_SEGMENT, "recent_roas": "?", "roas_change_pct": "?", "spend_share_pct": "?"}
        sit = (f"At the account level everything looks flat — but one audience, <b>{html.escape(o['segment'])}</b>, "
               f"is quietly outperforming: ROAS <b>{o['recent_roas']}</b> (up <b>+{o['roas_change_pct']}%</b>) on "
               f"just <b>{o['spend_share_pct']}%</b> of spend. It's buried inside bigger campaigns, so the "
               f"dashboards miss it entirely.")
        rec = (f"Launch a dedicated campaign for the {html.escape(o['segment'])} audience. This is net-new "
               "upside — feeding demand that already exists — not moving money off anything that's working.")
    elif root == "noise":
        sit = ("Nothing meaningful changed this week. Every campaign is within its normal week-to-week "
               "wobble — all moves under ~5%. There is no signal here, only noise.")
        rec = ("Do nothing. Reacting to random fluctuation — shuffling budgets on a quiet week — is one of "
               "the most common ways to quietly erode performance over time.")
    elif root == "tracking_outage":
        sit = (f"<b>{gn}</b>'s reported ROAS cratered <b>{_pct(g['roas'])}</b> — alarming at a glance. But "
               f"look closer: clicks are completely normal; only recorded <i>conversions</i> collapsed "
               f"(<b>{_pct(g['cvr'])}</b>). Real demand doesn't vanish overnight while clicks stay flat. "
               f"This is a <b>broken conversion-tracking pixel</b> — the sales are still happening, we just "
               f"stopped recording them.")
        rec = ("Fix the tracking, don't touch the budget. ⚠️ This is a trap: the intuitive move — pull money "
               "out of a 'failing' campaign — would be reacting to a measurement bug and would starve a "
               "campaign that's actually fine.")
    elif root == "seasonality":
        sit = ("Every campaign is down together this week, not just one. When the whole account softens "
               "uniformly, the cause is almost always <b>external seasonality</b> — a slow week, a holiday "
               "lull — not anything we did.")
        rec = ("Hold steady. ⚠️ Trap: shuffling budget between campaigns that are all down for the same "
               "external reason accomplishes nothing. Let the season pass.")
    elif root == "brand_demand_dip":
        sit = (f"The <b>Brand Search</b> campaign is down <b>{_pct(g['roas'])}</b> — fewer people are "
               f"searching our brand name this week. That's a market demand signal, not a campaign problem. "
               f"Brand is also our protected floor: it defends our name from competitors bidding on it.")
        rec = ("Hold. ⚠️ Trap: cutting Brand would be doubly wrong — it won't fix external demand, and it "
               "leaves our brand name exposed to competitors. Never source budget from the brand floor.")
    elif root == "learning_phase":
        days = next((v.get("last_edited_days_ago") for v in [sc_meta(sc, gid) for gid in GROUP_IDS] if v), "a few")
        sit = (f"<b>{gn}</b> was rebuilt {days} days ago, so it's still in its <b>learning phase</b> — the "
               f"platform's algorithm hasn't re-optimized yet, and the early numbers are noisy and "
               f"unreliable. It looks down <b>{_pct(g['roas'])}</b>, but that reading can't be trusted yet.")
        rec = ("Be patient — give it the full learning window before judging. ⚠️ Trap: acting on "
               "learning-phase noise means over-reacting to numbers that haven't settled.")
    elif root == "budget_cap":
        lost = next((v.get("lost_impression_share_budget_pct") for v in [sc_meta(sc, gid) for gid in GROUP_IDS] if v), "")
        sit = (f"<b>{gn}</b> is winning — efficient and improving — but it's <b>capped by its budget</b>, "
               f"losing about <b>{lost}%</b> of available impressions simply because it runs out of money "
               f"each day. This is proven demand we're leaving on the table.")
        rec = ("Increase its budget so it can capture the demand it's already earning. The fix is more "
               "money on a winner — not a shift between campaigns.")
    elif root == "landing_page_break":
        sit = (f"<b>{gn}</b>'s ROAS fell <b>{_pct(g['roas'])}</b> and conversions collapsed "
               f"(<b>{_pct(g['cvr'])}</b>) — which looks exactly like a tracking outage. But this time "
               f"the <b>bounce rate has spiked</b>: real visitors are still arriving (clicks and sessions "
               f"are normal), they're just leaving immediately. The landing page or checkout is broken.")
        rec = ("Fix the landing page/checkout — not the pixel and not the budget. ⚠️ Trap: the bounce spike "
               "is the only thing separating this from a tracking bug; miss it and you'll 'fix tracking' "
               "while real buyers keep bouncing off a broken page.")
    elif root == "funnel_leak":
        sit = (f"<b>{gn}</b>'s ROAS is down <b>{_pct(g['roas'])}</b>, but the ad funnel is healthy — "
               f"click-through and conversion rates are both normal. What collapsed is the <b>revenue per "
               f"conversion</b>: the ads are delivering, the money is leaking <i>downstream</i> "
               f"(refunds, a discount error, or degraded lead quality).")
        rec = ("Hold the ad budget and escalate the downstream leak. ⚠️ Trap: ROAS looks bad, so the "
               "instinct is to cut the campaign — but the ads are working; cutting them would starve a "
               "healthy channel and never touch the actual leak.")
    elif root == "over_saturation":
        sit = (f"<b>{gn}</b>'s ROAS fell <b>{_pct(g['roas'])}</b> — but not because the audience "
               f"decayed. We <b>ramped its spend up hard</b>, and the extra money bought its own worst "
               f"impressions: frequency climbed and conversions barely followed. We pushed it past its "
               f"efficient frontier.")
        rec = ("Pull the budget back to the efficient point — decrease, don't re-target. ⚠️ Trap: this "
               "looks like audience saturation (fix targeting), but the tell is that <i>spend rose</i>. "
               "The audience is fine; we simply over-invested.")
    elif root == "dead_campaign":
        sit = ("At the group level the account looks quiet — but cutting by <b>audience</b> reveals one "
               "segment burning spend far below break-even, and it stays there. Creative is fine, tracking "
               "is fine; it just doesn't convert. It's a rounding error inside every group, invisible to "
               "the rollup — only a segment-level scan (find_losers) can see it.")
        rec = ("Kill it and reclaim the spend. ⚠️ Trap: no refresh or re-target rescues a structurally "
               "unprofitable audience — and because it's tiny inside each group, the instinct is to ignore "
               "it while it quietly bleeds budget.")
    elif root == "multi":
        return _plan_narrative(sc, rows, opps)
    else:
        sit, rec = "", ""
    return f"<p>{sit}</p>", f"<p>{rec}</p>"


def sc_meta(sc, gid):
    """Recover a scenario's flags for a group (learning/budget-cap) without an env."""
    env = _META_CACHE.get(id(sc))
    return env.meta.get(gid, {}) if env else {}


_META_CACHE = {}


def _plan_narrative(sc, rows, opps):
    plan = sc["expected"]["plan"]
    by_group = {}
    for it in plan:
        by_group.setdefault(it["group"], []).append(it["action"])

    parts, recs = [], []
    for gid, actions in by_group.items():
        if gid is None:
            continue
        r = next((x for x in rows if x["gid"] == gid), None)
        gn = gname(gid)
        if "refresh_creative" in actions and "fix_targeting" in actions:
            parts.append(f"<b>{gn}</b> has <i>two</i> problems at once — a tired ad (clicks down "
                         f"{_pct(r['ctr'])}) <i>and</i> a targeting problem (conversion rate down {_pct(r['cvr'])})")
            recs.append(f"refresh {gn}'s creative <u>and</u> fix its targeting")
        elif "refresh_creative" in actions:
            parts.append(f"<b>{gn}</b>'s ad has gone stale (click-through down {_pct(r['ctr'])})")
            recs.append(f"refresh {gn}'s creative")
        elif "fix_targeting" in actions:
            parts.append(f"<b>{gn}</b> is reaching the wrong audience (conversion rate down {_pct(r['cvr'])})")
            recs.append(f"fix {gn}'s targeting")
    if any(it["group"] is None and it["action"] == "launch_campaign" for it in plan):
        seg = opps[0]["segment"] if opps else EMERGING_SEGMENT
        parts.append(f"and the <b>{html.escape(seg)}</b> audience is quietly outperforming — a new-campaign opportunity")
        recs.append(f"launch a campaign for the {html.escape(seg)} audience")

    sit = ("This week the account has <b>several independent things going on at once</b>, so no single "
           "move fixes it: " + "; ".join(parts) + ".")
    rec = ("A real recommendation is a <b>plan</b>, not one lever. Do all of it: " + "; ".join(recs) +
           ". A single-move answer would leave most of the value on the table — which is exactly what "
           "separates a plan from a guess.")
    return f"<p>{sit}</p>", f"<p>{rec}</p>"


def _answer_html(exp):
    if exp.get("plan"):
        items = "".join(
            f"<li><span class='act'>{html.escape(it['action'])}</span> — {html.escape(gname(it['group']))}</li>"
            for it in exp["plan"])
        return f"<div class='ans-kind'>PLAN — {len(exp['plan'])} actions</div><ul class='plan'>{items}</ul>"
    tgt = exp["acceptable_targets"][0] if exp["acceptable_targets"] else None
    tgt_txt = f" → <b>{html.escape(gname(tgt))}</b>" if tgt else ""
    return (f"<div class='ans-kind'>SINGLE ACTION</div>"
            f"<div class='act-big'>{html.escape(exp['action'])}{tgt_txt}</div>")


def _drill(env, gid):
    """Expandable list of the individual campaigns inside a group that moved."""
    gc = env.get_group_campaigns(gid, sort_by="roas_change", limit=8)
    body = "".join(
        f"<tr><td class='cn'>{html.escape(c['name'])}</td><td>${c['daily_spend']:.0f}/day</td>"
        f"<td>{c['recent_roas']}</td><td>{_pct(c['roas_change_pct'])}</td></tr>"
        for c in gc["campaigns"])
    return (f"<details class='drill'><summary>▸ drill into the {gc['n_campaigns']} campaigns inside "
            f"{html.escape(gname(gid))} — worst movers</summary>"
            f"<table class='dtable'><thead><tr><th>Campaign</th><th>Spend</th><th>ROAS</th><th>ROAS Δ</th></tr>"
            f"</thead><tbody>{body}</tbody></table>"
            f"<div class='drill-note'>showing {gc['showing']} of {gc['n_campaigns']} — the group rollup above "
            f"is the sum of all {gc['n_campaigns']}.</div></details>")


def _card(sc, env, verified):
    _META_CACHE[id(sc)] = env
    rows, opps, _ = _evidence(env)
    diff = sc["difficulty"]
    situation, recommendation = _narrative(sc, rows, opps)

    tr = ""
    for r in rows:
        cls = "moved" if r["moved"] else "quiet"
        tr += (f"<tr class='{cls}'><td>{r['gid']}</td><td class='gname'>{html.escape(r['name'])}</td>"
               f"<td>{_pct(r['roas'])}</td><td>{_pct(r['ctr'])}</td><td>{_pct(r['cvr'])}</td>"
               f"<td>{r['b']:.2f}</td><td class='flags'>{html.escape(r['flags'])}</td></tr>")
    opp_html = ""
    if opps:
        o = opps[0]
        opp_html = (f"<div class='opp'>🎯 Hidden opportunity — <b>{html.escape(o['segment'])}</b>: "
                    f"ROAS {o['recent_roas']} (+{o['roas_change_pct']}%) on only {o['spend_share_pct']}% of spend</div>")
    drill = "".join(_drill(env, r["gid"]) for r in rows if r["moved"])
    trap = "⚠️" in recommendation
    badge = "✓" if verified else "✗"
    exp = sc["expected"]
    if exp.get("plan"):
        actions_attr = " ".join(["plan"] + sorted({it["action"] for it in exp["plan"]}))
    else:
        actions_attr = exp["action"]
    return f"""
<div class="card" data-diff="{diff}" data-actions="{actions_attr}">
  <div class="chead">
    <span class="id">{html.escape(sc['id'])}</span>
    <span class="badge {diff}">{diff}</span>
    <span class="cname">{html.escape(sc['name'])}</span>
    {"<span class='trap'>trap</span>" if trap else ""}
    <span class="verify" title="the correct answer is provably present in the data">{badge}</span>
  </div>
  <div class="story">
    <div class="sec-label">💬 What's happening</div>
    {situation}
  </div>
  <div class="cbody">
    <div class="data">
      <div class="sec-label">The evidence (recent 14 days vs prior)</div>
      <table>
        <thead><tr><th>Grp</th><th>Campaign group</th><th>ROAS Δ</th><th>CTR Δ</th><th>CVR Δ</th><th>elast</th><th>flags</th></tr></thead>
        <tbody>{tr}</tbody>
      </table>
      {opp_html}
      {drill}
    </div>
    <div class="answer">
      <div class="sec-label">✅ Recommended action &amp; why</div>
      {recommendation}
      <div class="ans-box">{_answer_html(sc['expected'])}</div>
    </div>
  </div>
</div>"""


def build():
    base = generate_base()
    scenarios = generate()
    cards = "".join(_card(sc, ScenarioEnv(base, sc), validate(sc, base)) for sc in scenarios)
    counts = {d: sum(1 for s in scenarios if s["difficulty"] == d) for d in ("simple", "medium", "complex")}
    verified = sum(1 for s in scenarios if validate(s, base))

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CMO Copilot — Marketing Decision Benchmark (100 questions)</title>
<style>
@import url('https://api.fontshare.com/v2/css?f[]=satoshi@400,500,700,900&f[]=clash-display@600,700&display=swap');
/* CMO Copilot design system tokens — raghavmkarya.github.io/cmo-copilot-design-system */
:root {{ --bg:#F9F9F9; --card:#FFFFFF; --ink:#02021E; --mut:#6B6B78; --line:#E6E6E6;
  --moved:#FFF3EA; --simple:#9797FF; --medium:#FF8431; --complex:#C75A12;
  --ans:#F3F3FF; --accent:#F26A1B; --accent-strong:#C75A12; --story:#FFF3EA; --sidebar:#FFFFFF;
  --radius:16px; --shadow-sm:0 2px 8px rgba(2,2,30,.06); --shadow-md:0 8px 24px rgba(2,2,30,.08); }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#000000; --card:#0E0E16; --ink:#FFFFFF;
  --mut:#9CA3AF; --line:#262630; --moved:#1C1206; --ans:#0F0F1A; --accent:#FFA040; --accent-strong:#FF8431;
  --story:#160F06; --sidebar:#0A0A11; --shadow-sm:0 2px 8px rgba(0,0,0,.4); --shadow-md:0 8px 24px rgba(0,0,0,.5); }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink);
  font-family:'Satoshi',-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; font-size:15px; line-height:1.6; }}
.topbar {{ display:flex; align-items:baseline; gap:14px; flex-wrap:wrap; padding:16px 24px;
  background:var(--card); border-bottom:1px solid var(--line); }}
.brand {{ font-family:'Clash Display','Satoshi',sans-serif; font-weight:700; font-size:22px; letter-spacing:-.01em; }}
.brand .dot {{ color:var(--accent); }}
.tagline {{ color:var(--mut); font-size:13px; }}
.legend {{ font-size:12px; color:var(--mut); line-height:1.75; }}
.legend b {{ color:var(--ink); }}
.layout {{ display:grid; grid-template-columns:238px 1fr; max-width:1300px; margin:0 auto; }}
.sidebar {{ position:sticky; top:0; align-self:start; height:100vh; overflow:auto;
  padding:22px 18px; background:var(--sidebar); border-right:1px solid var(--line); }}
.sidebar h2 {{ font-family:'Clash Display','Satoshi',sans-serif; font-size:12px; text-transform:uppercase;
  letter-spacing:.08em; color:var(--mut); margin:0 0 16px; }}
.fgroup {{ margin-bottom:22px; }}
.flabel {{ font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:var(--mut); font-weight:700; margin-bottom:9px; }}
.sidebar button {{ display:block; width:100%; text-align:left; border:1px solid var(--line); background:var(--card);
  color:var(--ink); border-radius:8px; padding:7px 12px; margin-bottom:6px; cursor:pointer; font-size:13px;
  font-family:inherit; transition:border-color .12s, background .12s; }}
.sidebar button:hover {{ border-color:var(--accent); }}
.sidebar button.on {{ background:var(--accent); color:#fff; border-color:var(--accent); font-weight:600; box-shadow:var(--shadow-sm); }}
.count {{ font-size:12px; color:var(--mut); font-weight:600; margin:2px 0 22px; }}
.main {{ padding:24px 28px 64px; min-width:0; }}
@media (max-width:820px) {{ .layout {{ grid-template-columns:1fr; }}
  .sidebar {{ position:static; height:auto; border-right:none; border-bottom:1px solid var(--line); }} }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:var(--radius); margin-bottom:16px; overflow:hidden; box-shadow:var(--shadow-sm); }}
.chead {{ display:flex; align-items:center; gap:10px; padding:13px 18px; border-bottom:1px solid var(--line); }}
.id {{ font:600 13px ui-monospace,Menlo,monospace; color:var(--mut); }}
.cname {{ flex:1; font-family:'Clash Display','Satoshi',sans-serif; font-weight:600; font-size:16px; }}
.verify {{ color:var(--accent); font-weight:700; }}
.trap {{ font-size:11px; font-weight:700; color:#fff; background:#E5484D; padding:2px 8px; border-radius:999px; }}
.badge {{ font-size:11px; text-transform:uppercase; letter-spacing:.04em; font-weight:700; padding:2px 10px; border-radius:999px; color:#fff; }}
.badge.simple {{ background:var(--simple); }} .badge.medium {{ background:var(--medium); }} .badge.complex {{ background:var(--complex); }}
.story {{ padding:14px 18px; background:var(--story); border-bottom:1px solid var(--line); }}
.story p {{ margin:0; }}
.sec-label {{ font-size:11px; letter-spacing:.05em; color:var(--mut); font-weight:700; text-transform:uppercase; margin-bottom:6px; }}
.cbody {{ display:grid; grid-template-columns:1.35fr 1fr; }}
@media (max-width:760px) {{ .cbody {{ grid-template-columns:1fr; }} }}
.data {{ padding:14px 18px; border-right:1px solid var(--line); overflow-x:auto; }}
@media (max-width:760px) {{ .data {{ border-right:none; border-bottom:1px solid var(--line); }} }}
table {{ width:100%; border-collapse:collapse; font-size:12.5px; }}
th {{ text-align:right; color:var(--mut); font-weight:600; padding:3px 8px; border-bottom:1px solid var(--line); }}
th:nth-child(2) {{ text-align:left; }}
td {{ text-align:right; padding:3px 8px; font-variant-numeric:tabular-nums; }}
td:first-child {{ font:600 12px ui-monospace,monospace; }}
.gname {{ text-align:left; color:var(--mut); }}
.flags {{ text-align:left; color:var(--medium); font-size:11px; }}
tr.moved td {{ background:var(--moved); font-weight:600; }}
tr.quiet {{ opacity:.5; }}
.opp {{ margin-top:10px; padding:9px 11px; background:var(--ans); border-radius:8px; font-size:12.5px; }}
details.drill {{ margin-top:10px; border-top:1px solid var(--line); padding-top:8px; }}
details.drill summary {{ cursor:pointer; font-size:12px; color:var(--accent); font-weight:600; list-style:none; }}
details.drill summary::-webkit-details-marker {{ display:none; }}
details.drill[open] summary {{ margin-bottom:8px; }}
.dtable {{ width:100%; font-size:11.5px; margin-top:2px; }}
.dtable .cn {{ text-align:left; color:var(--ink); font-weight:500; max-width:230px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.drill-note {{ font-size:11px; color:var(--mut); margin-top:6px; font-style:italic; }}
.answer {{ padding:14px 18px; background:var(--ans); }}
.answer p {{ margin:0 0 10px; }}
.ans-box {{ border-top:1px dashed var(--line); padding-top:9px; }}
.ans-kind {{ font-size:10.5px; letter-spacing:.05em; color:var(--mut); font-weight:700; text-transform:uppercase; }}
.act-big {{ margin-top:3px; font:700 16px ui-monospace,monospace; color:var(--accent); }}
.plan {{ margin:6px 0 0; padding-left:18px; }}
.plan li {{ margin:2px 0; }}
.act {{ font:600 13px ui-monospace,monospace; color:var(--accent); }}
</style></head><body>
<header class="topbar">
  <span class="brand">CMO Copilot<span class="dot">.</span></span>
  <span class="tagline">Marketing Decision Benchmark — 100 situations CMO Copilot is graded on. Data &amp;
    questions generated by code (no AI in the writing); every answer verified from the numbers ({verified}/100 ✓).</span>
</header>
<div class="layout">
  <aside class="sidebar">
    <h2>Filters</h2>
    <div class="fgroup">
      <div class="flabel">Difficulty</div>
      <button class="on" data-g="diff" data-f="all">All · 100</button>
      <button data-g="diff" data-f="simple">Simple · 40</button>
      <button data-g="diff" data-f="medium">Medium · 40 (traps)</button>
      <button data-g="diff" data-f="complex">Complex · 20 (plans)</button>
    </div>
    <div class="fgroup">
      <div class="flabel">Recommended action</div>
      <button class="on" data-g="act" data-f="all">All actions</button>
      <button data-g="act" data-f="refresh_creative">refresh_creative</button>
      <button data-g="act" data-f="fix_targeting">fix_targeting</button>
      <button data-g="act" data-f="fix_landing_page">fix_landing_page</button>
      <button data-g="act" data-f="launch_campaign">launch_campaign</button>
      <button data-g="act" data-f="pause_campaign">pause_campaign</button>
      <button data-g="act" data-f="fix_tracking">fix_tracking</button>
      <button data-g="act" data-f="increase_budget">increase_budget</button>
      <button data-g="act" data-f="decrease_budget">decrease_budget</button>
      <button data-g="act" data-f="no_action">no_action</button>
      <button data-g="act" data-f="plan">multi-item plan</button>
    </div>
    <div class="count" id="count"></div>
    <div class="fgroup">
      <div class="flabel">Reading the evidence</div>
      <div class="legend"><b>ROAS Δ</b> return on ad spend change<br>
        <b>CTR Δ</b> click-through — are people clicking?<br>
        <b>CVR Δ</b> conversion rate — do clicks become sales?<br>
        <b>elast</b> room to scale (~0.9 lots · ~0.5 saturating)<br>
        Highlighted rows = campaigns that moved.</div>
    </div>
  </aside>
  <main class="main">{cards}</main>
</div>
<script>
const cards=[...document.querySelectorAll('.card')];
const state={{diff:'all',act:'all'}};
function apply(){{
  cards.forEach(c=>{{
    const okd = state.diff==='all' || c.dataset.diff===state.diff;
    const oka = state.act==='all' || c.dataset.actions.split(' ').includes(state.act);
    c.style.display = (okd && oka) ? '' : 'none';
  }});
  document.getElementById('count').textContent =
    cards.filter(c=>c.style.display!=='none').length + ' of 100 shown';
}}
document.querySelectorAll('.sidebar button').forEach(b=>b.onclick=()=>{{
  const g=b.dataset.g;
  document.querySelectorAll(`.sidebar button[data-g="${{g}}"]`).forEach(x=>x.classList.toggle('on',x===b));
  state[g]=b.dataset.f;
  apply();
}});
apply();
</script></body></html>"""

    out = Path(__file__).resolve().parent.parent / "benchmark_review.html"
    out.write_text(page)
    print(f"wrote {out}  ({len(scenarios)} questions, {verified} verified)")
    return out


if __name__ == "__main__":
    build()
