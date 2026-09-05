"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { MasterUploads } from "./components/master-uploads";

type Scope = "all" | "own_business" | "competitor";
type Geography = "country" | "state";
type Insight = { title: string; detail: string; business_scope: "own_business" | "competitor"; signal_ids: string[] };
type CloudTerm = { term: string; weight: number };
type EvidenceItem = {
  id: string; title: string; summary: string; state: string; category: string;
  business_scope: "own_business" | "competitor"; strength: "weak" | "strong";
  distinct_employee_count: number; last_seen_at: string;
  evidence: Array<{ observation_id: string; employee_code: string; claim: string; confidence: number; observed_at: string }>;
};
type WeeklyBrief = {
  summary: string; opportunities: Insight[]; threats: Insight[]; word_cloud: CloudTerm[];
  company_name: string; geography: string; business_scope: Scope; week_ending: string;
  generated_at: string; cached: boolean; available_states: string[]; signal_count: number; evidence: EvidenceItem[];
};

const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "/api/v1";

function todayInIndia(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}

function displayDate(value: string): string {
  return new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric" }).format(new Date(`${value}T12:00:00+05:30`));
}

function scopeLabel(scope: Scope): string {
  return scope === "own_business" ? "Own business" : scope === "competitor" ? "Competitors" : "All intelligence";
}

function EmptyItems({ kind }: { kind: string }) {
  return <p className="empty-intelligence">No evidence-backed {kind.toLowerCase()} identified for this selection.</p>;
}

export default function Home() {
  const [view, setView] = useState<"intelligence" | "admin">("intelligence");
  const [scope, setScope] = useState<Scope>("all");
  const [geography, setGeography] = useState<Geography>("country");
  const [state, setState] = useState("");
  const [weekEnding, setWeekEnding] = useState(todayInIndia);
  const [brief, setBrief] = useState<WeeklyBrief | null>(null);
  const [availableStates, setAvailableStates] = useState<string[]>([]);
  const [selectedInsight, setSelectedInsight] = useState<Insight | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  const loadBrief = useCallback(async (signal: AbortSignal) => {
    if (geography === "state" && !state) {
      setBrief(null);
      setLoading(false);
      setError("");
      return;
    }
    setLoading(true);
    setError("");
    const params = new URLSearchParams({ week_ending: weekEnding, business_scope: scope });
    if (geography === "state" && state) params.set("state", state);
    try {
      const response = await fetch(`${apiBase}/admin/weekly-intelligence?${params}`, { credentials: "same-origin", signal });
      const body = await response.json().catch(() => null) as WeeklyBrief | { detail?: string } | null;
      if (!response.ok) throw new Error(body && "detail" in body ? body.detail : "Weekly intelligence is unavailable.");
      const nextBrief = body as WeeklyBrief;
      setBrief(nextBrief);
      setAvailableStates(nextBrief.available_states);
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === "AbortError") return;
      setError(requestError instanceof Error ? requestError.message : "Weekly intelligence is unavailable.");
    } finally {
      if (!signal.aborted) setLoading(false);
    }
  }, [geography, scope, state, weekEnding]);

  useEffect(() => {
    const controller = new AbortController();
    const scheduled = window.setTimeout(() => void loadBrief(controller.signal), 0);
    return () => {
      window.clearTimeout(scheduled);
      controller.abort();
    };
  }, [loadBrief, refreshKey]);

  const selectedEvidence = useMemo(() => {
    if (!selectedInsight || !brief) return [];
    return brief.evidence.filter((item) => selectedInsight.signal_ids.includes(item.id));
  }, [brief, selectedInsight]);

  function downloadBrief() {
    if (!brief) return;
    const lines = [
      `WEEKLY MARKET INTELLIGENCE — ${brief.geography.toUpperCase()}`,
      `Week ending ${displayDate(brief.week_ending)} · ${scopeLabel(brief.business_scope)}`, "", brief.summary, "",
      "BIGGEST OPPORTUNITIES", ...brief.opportunities.map((item, index) => `${index + 1}. ${item.title}: ${item.detail}`), "",
      "BIGGEST THREATS", ...brief.threats.map((item, index) => `${index + 1}. ${item.title}: ${item.detail}`), "",
      `KEY THEMES: ${brief.word_cloud.map((item) => item.term).join(", ")}`,
    ];
    const url = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/plain;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `field-intelligence-${brief.week_ending}.txt`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <main className="app-shell weekly-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">FI</span><div><strong>Field Intelligence</strong><small>Agricultural inputs</small></div></div>
        <nav aria-label="Primary navigation">
          <button className={view === "intelligence" ? "nav-item active" : "nav-item"} onClick={() => setView("intelligence")} type="button"><span className="nav-dot" />Weekly intelligence</button>
          <button className={view === "admin" ? "nav-item active" : "nav-item"} onClick={() => setView("admin")} type="button"><span className="nav-dot" />Admin setup</button>
        </nav>
        <div className="channel-health live"><span className="status-dot" /><div><strong>WhatsApp channel</strong><small>Live · accepting field reports</small></div></div>
        <div className="profile-row"><span className="avatar">A</span><div><strong>Admin</strong><small>Company Admin</small></div></div>
      </aside>

      <section className="workspace">
        <header className="topbar weekly-topbar">
          <div><p className="eyebrow">Rolling seven-day view</p><h1>{view === "admin" ? "Admin setup" : "Weekly market intelligence"}</h1></div>
          {view === "intelligence" && <div className="top-actions"><button className="quiet-button" disabled={!brief} onClick={downloadBrief} type="button">Download brief</button><button className="primary-button" onClick={() => setRefreshKey((value) => value + 1)} type="button">Reload dashboard</button></div>}
        </header>

        <div className="content weekly-content">
          {view === "admin" ? <MasterUploads /> : <>
            <section className="intelligence-controls" aria-label="Intelligence filters">
              <div className="control-group"><span>Market level</span><div className="choice-row">{(["country", "state"] as Geography[]).map((option) => <button className={geography === option ? "choice active" : "choice"} key={option} onClick={() => { setGeography(option); setSelectedInsight(null); if (option === "state") setBrief(null); }} type="button">{option === "country" ? "Country" : "State"}</button>)}</div></div>
              {geography === "state" && <label className="select-control"><span>State</span><select onChange={(event) => { setState(event.target.value); setSelectedInsight(null); }} value={state}><option value="">Select state</option>{availableStates.map((item) => <option key={item}>{item}</option>)}</select></label>}
              <label className="select-control"><span>Week ending</span><input max={todayInIndia()} onChange={(event) => { setWeekEnding(event.target.value); setSelectedInsight(null); }} type="date" value={weekEnding} /></label>
              <div className="control-group scope-control"><span>Scope</span><div className="choice-row">{(["all", "own_business", "competitor"] as Scope[]).map((option) => <button className={scope === option ? "choice active" : "choice"} key={option} onClick={() => { setScope(option); setSelectedInsight(null); }} type="button">{scopeLabel(option)}</button>)}</div></div>
            </section>

            {geography === "state" && !state && <section className="dashboard-error"><strong>Select a state</strong><p>Choose a state from the employee master to prepare its seven-day brief.</p></section>}

            {error && <section className="dashboard-error" role="alert"><strong>Could not prepare the weekly brief</strong><p>{error}</p><button className="quiet-button" onClick={() => setRefreshKey((value) => value + 1)} type="button">Try again</button></section>}
            {loading && <section className="brief-loading"><span className="spinner" /><div><strong>Synthesising field intelligence</strong><small>Reading evidence-backed signals for the selected week…</small></div></section>}

            {!loading && brief && !error && <>
              <section className="weekly-hero"><div><p className="eyebrow">{brief.geography} · Week ending {displayDate(brief.week_ending)}</p><h2>What happened in the market</h2><p className="weekly-summary">{brief.summary}</p></div><div className="brief-provenance"><strong>{brief.signal_count}</strong><span>evidence-backed {brief.signal_count === 1 ? "signal" : "signals"}</span><small>{brief.cached ? "Cached brief" : "Freshly synthesised"}</small></div></section>
              <section className="opportunity-threat-grid">
                <article className="weekly-card opportunity-card"><div className="weekly-card-heading"><span className="card-symbol">↗</span><div><p className="eyebrow">Potential upside</p><h2>Biggest opportunities</h2></div></div>{brief.opportunities.length ? brief.opportunities.map((item, index) => <button className="ranked-insight" key={`${item.title}-${index}`} onClick={() => setSelectedInsight(item)} type="button"><span className="rank">0{index + 1}</span><div><strong>{item.title}</strong><p>{item.detail}</p><small>{item.business_scope === "own_business" ? "Own business" : "Competitor"} · View evidence</small></div><span className="insight-arrow">→</span></button>) : <EmptyItems kind="Opportunities" />}</article>
                <article className="weekly-card threat-card"><div className="weekly-card-heading"><span className="card-symbol">!</span><div><p className="eyebrow">Watch closely</p><h2>Biggest threats</h2></div></div>{brief.threats.length ? brief.threats.map((item, index) => <button className="ranked-insight" key={`${item.title}-${index}`} onClick={() => setSelectedInsight(item)} type="button"><span className="rank">0{index + 1}</span><div><strong>{item.title}</strong><p>{item.detail}</p><small>{item.business_scope === "own_business" ? "Own business" : "Competitor"} · View evidence</small></div><span className="insight-arrow">→</span></button>) : <EmptyItems kind="Threats" />}</article>
              </section>
              <section className="weekly-card word-cloud-card"><div className="weekly-card-heading"><span className="card-symbol cloud">Aa</span><div><p className="eyebrow">Conversation themes</p><h2>This week in words</h2></div></div>{brief.word_cloud.length ? <div className="word-cloud" aria-label="Weekly word cloud">{brief.word_cloud.map((item) => <span key={item.term} style={{ fontSize: `${14 + Math.round(item.weight / 7)}px`, opacity: .55 + item.weight / 220 }}>{item.term}</span>)}</div> : <EmptyItems kind="Themes" />}</section>
            </>}
          </>}
        </div>
      </section>

      {selectedInsight && <div className="evidence-backdrop" onMouseDown={(event) => { if (event.currentTarget === event.target) setSelectedInsight(null); }} role="presentation"><section aria-labelledby="evidence-title" aria-modal="true" className="evidence-drawer" role="dialog"><div className="evidence-heading"><div><p className="eyebrow">Supporting field evidence</p><h2 id="evidence-title">{selectedInsight.title}</h2><p>{selectedInsight.detail}</p></div><button aria-label="Close evidence" className="close-button" onClick={() => setSelectedInsight(null)} type="button">×</button></div>{selectedEvidence.map((signal) => <article className="evidence-signal" key={signal.id}><div className="evidence-signal-title"><span className={`strength ${signal.strength}`}>{signal.strength}</span><strong>{signal.title}</strong></div><div className="signal-meta"><span>{signal.state}</span><span>{signal.category.replaceAll("_", " ")}</span><span>{signal.distinct_employee_count} employees</span></div>{signal.evidence.map((item) => <blockquote key={item.observation_id}><p>“{item.claim}”</p><footer>{item.employee_code} · AI confidence {Math.round(item.confidence * 100)}%</footer></blockquote>)}</article>)}</section></div>}
    </main>
  );
}
