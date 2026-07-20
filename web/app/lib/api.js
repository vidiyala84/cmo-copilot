const BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

async function get(path) {
  const r = await fetch(BASE + path, { cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return r.json();
}
async function post(path, body) {
  const r = await fetch(BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return r.json();
}

export const api = {
  base: BASE,
  health: () => get("/api/health"),
  scenarios: () => get("/api/scenarios"),
  baseline: (live) => get("/api/baseline" + (live ? "?live=true" : "")),
  overview: (refresh) => get("/api/overview" + (refresh ? "?refresh=true" : "")),
  liveBenchmark: () => get("/api/live/benchmark"),
  liveMemory: () => get("/api/live/memory"),
  liveMemSoc: () => get("/api/live/memsoc"),
  data: () => get("/api/data"),
  scaling: () => get("/api/scaling"),
  questions: () => get("/api/questions"),
  liveRun: (scenario, approach) => post("/api/live/run", { scenario, approach }),
  track1: (sessions, live) => post("/api/track1/run", { sessions, live: !!live }),
  track3all: () => get("/api/track3/all"),
  track3: (sid, live, fresh) => get("/api/track3/" + sid + (live ? `?live=true${fresh ? "&fresh=true" : ""}` : "")),
  track4: (body) => post("/api/track4/run", body),
};
