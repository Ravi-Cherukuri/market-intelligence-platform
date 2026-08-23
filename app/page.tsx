"use client";

import { useMemo, useState } from "react";

import { MasterUploads } from "./components/master-uploads";

type Signal = {
  title: string;
  context: string;
  state: string;
  category: string;
  strength: "Strong" | "Weak";
  sources: number;
  age: string;
  tone: "amber" | "green" | "blue" | "red";
};

const signals: Signal[] = [
  {
    title: "Competitor fungicide scheme expanding",
    context: "Two dealers report a 10+1 case scheme on Triazole Mix 250 ml packs.",
    state: "Maharashtra",
    category: "Pricing & schemes",
    strength: "Strong",
    sources: 4,
    age: "42 min",
    tone: "amber",
  },
  {
    title: "Early sucking-pest incidence in cotton",
    context: "Jassid pressure reported after intermittent rainfall; severity remains localised.",
    state: "Gujarat",
    category: "Pest incidence",
    strength: "Strong",
    sources: 3,
    age: "1 hr",
    tone: "red",
  },
  {
    title: "Micronutrient stock thinning in channel",
    context: "Zinc EDTA availability is tightening across two distributor points.",
    state: "Karnataka",
    category: "Availability",
    strength: "Weak",
    sources: 1,
    age: "2 hrs",
    tone: "blue",
  },
  {
    title: "New biological seed treatment sighted",
    context: "A new Trichoderma formulation was photographed at a retailer launch event.",
    state: "Madhya Pradesh",
    category: "New launches",
    strength: "Weak",
    sources: 1,
    age: "3 hrs",
    tone: "green",
  },
];

const navigation = [
  "Overview",
  "Signals",
  "Evidence inbox",
  "Reports",
  "Intelligence studio",
  "Employees & territories",
  "Product masters",
  "Data retention",
  "Settings",
];

function Metric({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <article className="metric-card">
      <p>{label}</p>
      <strong>{value}</strong>
      <span>{note}</span>
    </article>
  );
}

export default function Home() {
  const [active, setActive] = useState("Overview");
  const [filter, setFilter] = useState<"All" | "Strong" | "Weak">("All");
  const filteredSignals = useMemo(
    () => signals.filter((signal) => filter === "All" || signal.strength === filter),
    [filter],
  );

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">FI</span>
          <div>
            <strong>Field Intelligence</strong>
            <small>Agricultural inputs</small>
          </div>
        </div>

        <nav aria-label="Primary navigation">
          {navigation.map((item) => (
            <button
              className={active === item ? "nav-item active" : "nav-item"}
              key={item}
              onClick={() => setActive(item)}
              type="button"
            >
              <span className="nav-dot" />
              {item}
            </button>
          ))}
        </nav>

        <div className="channel-health">
          <span className="status-dot" />
          <div>
            <strong>WhatsApp channel</strong>
            <small>Awaiting pilot credentials</small>
          </div>
        </div>
        <div className="profile-row">
          <span className="avatar">A</span>
          <div>
            <strong>Admin</strong>
            <small>Company Admin</small>
          </div>
          <button aria-label="Open account menu" type="button">•••</button>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">Sunday, 9 August</p>
            <h1>{active}</h1>
          </div>
          <div className="top-actions">
            <button className="quiet-button" type="button">Download brief</button>
            <button className="primary-button" type="button">Ask intelligence</button>
          </div>
        </header>

        <div className="content">
          <section className="welcome-panel">
            <div>
              <p className="eyebrow">Market pulse</p>
              <h2>Good morning. Four signals need attention.</h2>
              <p>
                Field activity is concentrated in Maharashtra and Gujarat today. Pricing schemes and
                early pest incidence are the strongest repeated themes.
              </p>
            </div>
            <div className="pulse-score">
              <span>Signal coverage</span>
              <strong>7 states</strong>
              <small>38 active reporters today</small>
            </div>
          </section>

          <section className="metric-grid" aria-label="Today’s intelligence metrics">
            <Metric label="Field conversations" value="126" note="+18% versus yesterday" />
            <Metric label="Strong signals" value="08" note="Corroborated by 2+ employees" />
            <Metric label="Evidence awaiting review" value="14" note="6 unmatched products" />
            <Metric label="States reporting" value="07" note="of 12 active states" />
          </section>

          <MasterUploads />

          <section className="main-grid">
            <article className="panel signals-panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Live intelligence</p>
                  <h2>Signals developing now</h2>
                </div>
                <div className="segment-control" aria-label="Filter signals">
                  {(["All", "Strong", "Weak"] as const).map((option) => (
                    <button
                      className={filter === option ? "selected" : ""}
                      key={option}
                      onClick={() => setFilter(option)}
                      type="button"
                    >
                      {option}
                    </button>
                  ))}
                </div>
              </div>

              <div className="signal-list">
                {filteredSignals.map((signal) => (
                  <article className="signal-row" key={signal.title}>
                    <span className={`signal-icon ${signal.tone}`} aria-hidden="true" />
                    <div className="signal-copy">
                      <div className="signal-title-row">
                        <h3>{signal.title}</h3>
                        <span className={`strength ${signal.strength.toLowerCase()}`}>
                          {signal.strength}
                        </span>
                      </div>
                      <p>{signal.context}</p>
                      <div className="signal-meta">
                        <span>{signal.state}</span>
                        <span>{signal.category}</span>
                        <span>{signal.sources} employees</span>
                        <span>{signal.age} ago</span>
                      </div>
                    </div>
                    <button className="arrow-button" aria-label={`Open ${signal.title}`} type="button">→</button>
                  </article>
                ))}
              </div>
            </article>

            <aside className="side-column">
              <article className="panel coverage-panel">
                <div className="panel-heading compact">
                  <div>
                    <p className="eyebrow">Participation</p>
                    <h2>State coverage</h2>
                  </div>
                </div>
                {[
                  ["Maharashtra", 86],
                  ["Gujarat", 72],
                  ["Karnataka", 58],
                  ["Madhya Pradesh", 44],
                ].map(([state, score]) => (
                  <div className="coverage-row" key={state}>
                    <div><span>{state}</span><small>{score}% reporting</small></div>
                    <span className="progress"><i style={{ width: `${score}%` }} /></span>
                  </div>
                ))}
              </article>

              <article className="panel activity-panel">
                <p className="eyebrow">Recent evidence</p>
                <h2>Field stream</h2>
                <div className="activity-item">
                  <span className="activity-type">VN</span>
                  <div><strong>EMP-1842 · Maharashtra</strong><p>Voice note · competitor price</p><small>8 minutes ago</small></div>
                </div>
                <div className="activity-item">
                  <span className="activity-type photo">PH</span>
                  <div><strong>EMP-0931 · Gujarat</strong><p>Photo · crop incidence</p><small>17 minutes ago</small></div>
                </div>
                <div className="activity-item">
                  <span className="activity-type text">TX</span>
                  <div><strong>EMP-2204 · Karnataka</strong><p>Text · stock availability</p><small>24 minutes ago</small></div>
                </div>
              </article>
            </aside>
          </section>
        </div>
      </section>
    </main>
  );
}
