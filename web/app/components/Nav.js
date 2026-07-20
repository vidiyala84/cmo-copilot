"use client";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/app/lib/api";

const LINKS = [
  { href: "/", ico: "◧", label: "Overview", tag: "bench" },
  { href: "/data", ico: "▦", label: "Data", tag: "source" },
  { href: "/questions", ico: "❓", label: "5 Questions", tag: "robust" },
  { href: "/track1", ico: "◔", label: "Memory", tag: "T1" },
  { href: "/track3", ico: "⚖", label: "Society", tag: "T3" },
  { href: "/memsoc", ico: "◈", label: "Mem + Society", tag: "combo" },
  { href: "/track4", ico: "⚡", label: "Autopilot", tag: "T4" },
  { href: "/scaling", ico: "▲", label: "Scaling", tag: "stress" },
];

export default function Nav() {
  const path = usePathname();
  const [provider, setProvider] = useState(null);
  useEffect(() => { api.health().then((h) => setProvider(h.provider)).catch(() => {}); }, []);
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="dot">A</div>
        <div>
          <h1>CMO Copilot</h1>
          <small>marketing-decision copilot</small>
        </div>
      </div>
      <nav className="nav">
        {LINKS.map((l) => (
          <Link key={l.href} href={l.href} className={path === l.href ? "active" : ""}>
            <span className="ico">{l.ico}</span>
            {l.label}
            <span className="tag">{l.tag}</span>
          </Link>
        ))}
      </nav>
      <div className="foot">
        <div className="provider-badge">
          <span className="live" /> {provider ? `${provider} · live` : "connecting…"}
        </div>
        <div>One problem, three architectures. Live on real Qwen.</div>
      </div>
    </aside>
  );
}
