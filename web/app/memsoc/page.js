"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Spinner, Badge, ErrorBox } from "../components/ui";
import MemoryReport from "../components/MemoryReport";

export default function MemSoc() {
  const [rep, setRep] = useState(null);
  const [scen, setScen] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);

  useEffect(() => {
    api.scenarios().then(setScen).catch(setErr);
    api.liveMemSoc().then((r) => { if (r && r.ready) setRep(r); }).catch(setErr).finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <div className="page-head">
        <div className="eyebrow" style={{ color: "var(--violet)" }}>Memory + Society · the composed system</div>
        <h2>The layers, stacked</h2>
        <p>
          The four-agent <strong>society</strong> does the hard diagnosis; on top of it, <strong>memory</strong>{" "}
          enforces the rules it has learned and corrects the exact situations that backfired in earlier sessions.
          Each decision below shows the society’s answer (the “baseline”) and what memory changed. This is the best
          performer in the whole benchmark — memory works far better bolted onto structure than on a lone model.
        </p>
      </div>

      <div className="row" style={{ marginBottom: 18 }}>
        <Badge tone="green">⚡ live (cached 5-session run)</Badge>
        {rep && <Badge tone="blue">society decides → memory corrects</Badge>}
      </div>

      <ErrorBox error={err} />
      {loading && <Spinner label="Loading live Memory+Society run…" />}
      {!loading && rep && !rep.per_session && (
        <div className="callout">The Memory+Society live run hasn’t been computed yet.</div>
      )}

      {rep && rep.per_session && (
        <MemoryReport rep={rep} scen={scen} baselineLabel="What the society decided (before memory)" />
      )}
    </div>
  );
}
