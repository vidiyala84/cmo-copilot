# Architecture — One Problem, Three Architectures

Diagrams render natively on GitHub (Mermaid). One CMO decision — *"ROAS dropped this
week; where should the budget go?"* — solved three ways on **one shared foundation**,
so every score delta is architectural, not data or model luck.

**Model:** Qwen (Qwen3-235B / `qwen-plus` / `qwen-flash` / `qwen-max`) served from
**Alibaba Cloud Model Studio (DashScope)** via a single provider seam (`llm.py` +
`config.py`, `LLM_PROVIDER=dashscope`). Every component also runs in a deterministic
`--mock` mode for offline CI.

---

## System / deployment topology — how Qwen Cloud connects to the backend & clients

```mermaid
flowchart LR
    subgraph CLIENTS["Clients / frontends"]
        cli["CLI<br/>benchmark.py · bench_live.py"]
        web["Web UI (Next.js) +<br/>presentation.html · benchmark_review.html"]
        mcpc["Any MCP client<br/>Qwen agent via bridge · IDE · Claude"]
    end

    subgraph ACLOUD["Alibaba Cloud — ECS / Function Compute (Docker)"]
        api["CMO Copilot backend · FastAPI<br/>api/main.py"]
        mcpsrv["MCP server · mcp_server.py<br/>7 tools over Model Context Protocol"]
        subgraph CORE["CMO Copilot core"]
            society["6-agent Society"]
            memory["Learned-gate Memory<br/>SQLite + decision tree"]
            toolbelt["Tool belt · tools.py<br/>group rollup → O(1) context"]
            data[("Deterministic account<br/>~300 campaigns × 90 days")]
        end
    end

    ms["Qwen Cloud · Alibaba Cloud Model Studio<br/>qwen-plus · qwen-flash · qwen-max · text-embedding-v3"]

    cli --> api
    web --> api
    mcpc --> mcpsrv
    api --> society --> toolbelt --> data
    api --> memory --> toolbelt
    mcpsrv --> toolbelt
    society -. LLM tool-calls .-> ms
    memory -. embeddings .-> ms
    api -. DASHSCOPE_API_KEY .-> ms

    classDef cloud fill:#FFF3EA,stroke:#F26A1B,color:#02021E
    class ms cloud
```

The **backend (FastAPI)** and the **MCP server** run on **Alibaba Cloud**; both call **Qwen on
Alibaba Cloud Model Studio** (chat models + embeddings) through the provider seam. Clients — the
CLI, the web UI, or any MCP client — reach the same audited, group-rollup tool belt. *(This is
the diagram to screenshot for the Devpost "Architecture Diagram" field.)*

---

## 0. Shared foundation

The reusable substrate all three tracks are built on: same data, same tool belt, same
scorer.

```mermaid
flowchart TD
    subgraph DATA["Data — deterministic (seed 42)"]
        cfg["config.py<br/>5 campaign GROUPS + constraints"]
        pf["portfolio.py<br/>5 groups → ~300 live campaigns"]
        dg["datagen.py<br/>90 days spend/clicks/convs/revenue"]
        cfg --> pf --> dg
    end

    subgraph ENV["ScenarioEnv (tools.py) — the shared tool belt"]
        t1["get_campaign_metrics()<br/><i>GROUP rollup — O(groups) context</i>"]
        t2["get_group_campaigns()<br/><i>drill-down, 25-row cap</i>"]
        t3["get_benchmarks()"]
        t4["forecast_roas() / diagnose_drivers()"]
        t5["find_opportunities()<br/><i>cross-group segment scan</i>"]
        t6["propose_reallocation()<br/><i>deterministic constraint validator</i>"]
        t7["apply_reallocation()<br/><i>sandbox + run-manifest ledger</i>"]
        t8["send_approval_request()"]
    end

    subgraph EVAL["Evaluation"]
        sc["scenarios.py<br/>11 scenarios · known answers · traps"]
        hn["harness.py<br/>score = 0.4 root cause + 0.4 action + 0.2 sourcing"]
        runs[("runs/*.json<br/>results + transcripts")]
    end

    llm["llm.py — provider seam<br/>DashScope (Qwen Cloud) | mock"]

    dg --> ENV
    ENV --> hn
    sc --> hn
    hn --> runs
    llm -.serves.-> ENV

    classDef trap fill:#fde,stroke:#c69
    class sc trap
```

**Why the group/campaign split matters (the scaling story).** A VP-Growth reasons about
**5 groups**, not 300 campaigns. `get_campaign_metrics` rolls up to group level (~5 rows,
~500 tokens) *no matter how many campaigns sit underneath*; `get_group_campaigns` drills
down only on request, hard-capped at 25 rows. Dumping the whole account is O(N) in tokens
and **blows the 32k context window around 500–1,000 campaigns** (measured in
`runs/scaling.json`) — this architecture keeps context ~O(1).

---

## 1. Track 1 — MemoryAgent

The same agent gets measurably better across sessions: it recalls corrections and the
outcomes of its own past decisions, under a hard context budget, with a real forgetting
policy.

```mermaid
flowchart LR
    q["CMO question"] --> MA

    subgraph MA["MemoryAgent (track1/memory_agent.py)"]
        direction TB
        recall["retriever.py<br/>top-k by relevance × recency × outcome-weight<br/>≤ 1,500 tokens"]
        base["base agent .decide()<br/>+ injected recall"]
        write["write outcome memory<br/>post-decision"]
        forget["forgetting policy<br/>half-life decay · contradiction demotion · staleness"]
        recall --> base --> write --> forget
    end

    subgraph STORES["memory_store.py — SQLite, 3 stores"]
        pref[("preference<br/>durable user rules")]
        out[("outcome<br/>did X → worked/backfired")]
        epi[("episode<br/>compressed run summaries")]
    end

    STORES -. recall .-> recall
    forget -. persist .-> STORES
    base --> dec["decision + trace"]

    runner["session_runner.py<br/>5 sessions, memory persists between runs"] -.drives.-> MA
```

**Money-shot:** the accuracy-over-sessions curve climbing (mock: **4.8 → 10.8 / 11**)
while the baseline stays flat at 4.8 and tokens/decision stay bounded.

---

## 2. Track 3 — Agent Society

Four specialists argue under a structured protocol; a deterministic Risk veto and a coded
ruling policy resolve conflicts. Every decision writes a full transcript.

```mermaid
flowchart TD
    q["CMO question"] --> coord

    subgraph SOC["Society (track3/society.py)"]
        analyst["🔍 Analyst<br/>diagnosis"]
        forecaster["📈 Forecaster<br/>eager optimizer"]
        risk["🛡️ Risk Officer<br/>deterministic constraint veto"]
        coord["🧭 Coordinator<br/>synthesis"]
    end

    coord --> analyst & forecaster & risk

    subgraph PROTO["Protocol (track3/protocol.py)"]
        submit["each submits: claim + evidence + confidence"]
        conflict{"conflict or<br/>Risk veto?"}
        debate["bounded debate<br/>≤ 2 rebuttal rounds"]
        rule["ruling policy:<br/>1. Risk veto = ABSOLUTE<br/>2. evidence quality<br/>3. confidence<br/>4. conservative default"]
        submit --> conflict
        conflict -- yes --> debate --> rule
        conflict -- no --> rule
    end

    analyst & forecaster & risk --> submit
    rule --> out["decision + full transcript<br/>(≥1 resolved conflict)"]

    classDef veto fill:#fde,stroke:#c69
    class risk veto
```

**Money-shot:** the **S07** transcript — Forecaster wants to cut the brand campaign, the
**Risk Officer vetoes** ("would breach the $2,000 brand floor"), the Coordinator holds.
Mock: **9.0 / 11 vs 4.8 baseline (+4.2)**, solves all three traps.

---

## 3. Track 4 — Autopilot

No one asks the agent anything: an alert fires and the pipeline carries the work to a
sandboxed execution, pausing only at a human gate. Every terminal state is safe.

```mermaid
flowchart LR
    alert(["⚠️ alert fires<br/>alerts.py"]) --> triage

    triage{"triage<br/>trivial dip?"}
    triage -- yes --> exit1["exit: ignored"]
    triage -- no --> diagnose

    diagnose["diagnose<br/>mock | live society"] --> propose

    propose["propose<br/>validate + ≤2 replans"] --> gate

    gate{"human gate (gate.py)<br/>approve / adjust / reject<br/>+ expiry"}
    gate -- reject/expire --> exit2["exit: held<br/>(no execution)"]
    gate -- approve --> exec

    subgraph EXEC["execute (faults.py)"]
        run["sandbox apply<br/>idempotent + run-manifest ledger"]
        fault{"fault?<br/>api500 / timeout"}
        run --> fault
        fault -- yes --> retry["retry ×2 → partial rollback"]
    end

    exec --> monitor["monitor 14 compressed days<br/>monitor.py"]
    monitor --> guard{"guardrail<br/>breach?"}
    guard -- yes --> rollback["auto-rollback<br/>reverse_manifest()"]
    guard -- no --> report
    retry --> notify["notify human"] --> report
    rollback --> report
    report(["closing report<br/>every number → tool-call ID"])

    approvals[("runs/approvals.jsonl<br/>zero exec without a record")]
    gate -.writes.-> approvals

    classDef safe fill:#dfe,stroke:#6b9
    class exit1,exit2,report safe
```

**Money-shot:** the rehearsed failure — inject `api500` mid-execution → retry → partial
rollback → human notification → terminal state **`failed_safe`**. Mock: **11/11 end safe**,
5 execute, 1 auto-rolls-back, **zero unapproved executions**.

---

## 4. Composite — Memory × Society (the headline)

The layers compose: the society does the hard diagnosis; memory *enforces* recalled rules
and *corrects* the situations that backfired before.

```mermaid
flowchart LR
    q["CMO question"] --> mem
    subgraph COMPOSITE["Memory × Society"]
        mem["MemoryAgent wrapper<br/>recall → … → learn"]
        soc["Agent Society<br/>as the diagnosis engine"]
        mem -->|inject recalled rules| soc
        soc -->|decision| mem
    end
    mem --> out["decision + trace"]

    note["Live Qwen, avg over 5 CMO questions:<br/>direct 48% · told-every-rule 64.8% · society 68% · <b>Memory×Society 86.4%</b>"]
```

> **The takeaway:** a smart model is table stakes. The measurable wins come from
> architecture — a deterministic policy gate, a specialist society, and memory that
> corrects recurring mistakes — and those layers compose. Same model throughout.

_(Live percentages are from the head-to-head benchmark; see `SUBMISSION.md` and
`runs/` for the sourced numbers.)_

---

## 5. Society + Memory — the memory that *learns* which calls to override

The converged architecture (`track3/society.py` + `track1/memory_gates.py`). The 6-agent
society reasons; the memory learns, from experience, which of its calls to override — validates
the override *mattered* on history, and enforces it deterministically. **74% → 100% over four
sessions, stable, zero LLM calls at enforcement.**

```mermaid
flowchart TD
    q["CMO question"] --> obs["OBSERVE — raw feature vector<br/>funnel drops · elasticity · 2nd-worst group<br/>roas spread · flags · brand · opportunity lift"]
    obs --> match{"a VALIDATED gate<br/>for this situation?"}

    match -- yes --> enforce["ENFORCE deterministically<br/>(a match, not an LLM re-read)<br/><i>0 LLM calls</i>"]
    match -- no --> soc

    subgraph SOC["6-agent Society (the reasoning base)"]
        soc["🔍 Analyst · 📈 Forecaster · 🛡️ Risk veto<br/>🧭 Coordinator · 🗂️ Portfolio Planner · 🌱 Growth Lead"]
    end

    enforce --> dec["decision"]
    soc --> dec
    dec --> outcome["OUTCOME — what actually worked<br/>(ground-truth episode)"]

    subgraph MEM["Memory (learns the gates)"]
        hist[("episode history<br/>features → what worked → was the base wrong?")]
        tree["LEARN — fit a decision tree each session<br/>(discovers the thresholds itself)"]
        val["VALIDATE — enforce a leaf only if history backs it:<br/>support · purity · <b>lift &gt; 0</b> (did the change matter?)"]
        hist --> tree --> val
    end

    outcome -.append.-> hist
    val -.arms the gates for next session.-> match

    classDef win fill:#dfe,stroke:#6b9
    class enforce win
```

**Why it's stable where prose-memory wasn't:** the tree learns from the *fixed ground-truth
outcomes*, not a fuzzy note the LLM re-interprets — so application is noise-free, and a leaf
can't drift on one anecdote (it needs historical support + lift to fire). The learned tree is
**identical across a deterministic base and a live-Qwen base**, because it's learning the
*task's* structure, not the base's quirks.

> **The takeaway:** a specialist society reasons; a memory learns *which of its calls to
> override* — from experience, validated against its own history, enforced deterministically.
> 27% → 100% on the same benchmark, and it holds.
