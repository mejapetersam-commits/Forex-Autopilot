import { AlertTriangle, CheckCircle2, Clock3, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";
import type { ReleaseReadinessGate, ReleaseReadinessResponse } from "./api";

function Status({ good, children }: { good: boolean; children: ReactNode }) {
  return <span className={`status ${good ? "good" : "bad"}`}><i />{children}</span>;
}

function Gate({ item }: { item: ReleaseReadinessGate }) {
  const passed = item.status === "passed";
  const waiting = item.status === "awaiting_activity" || item.status === "awaiting_telemetry" || item.status === "operator_validation_required";
  return <article className="readiness-gate">
    <div className="readiness-gate-icon">{passed ? <CheckCircle2 size={17}/> : waiting ? <Clock3 size={17}/> : <AlertTriangle size={17}/>}</div>
    <div className="readiness-gate-copy"><b>{item.label}</b><span>{item.detail}</span></div>
    <Status good={passed}>{item.status.replaceAll("_", " ").toUpperCase()}</Status>
  </article>;
}

export default function ReleaseReadiness({ data }: { data: ReleaseReadinessResponse | null }) {
  return <section className="panel release-readiness">
    <div className="section-head">
      <div><div className="eyebrow">RELEASE & DEMO VALIDATION GATES</div><h2>System readiness audit</h2><p className="subhead">Automated evidence is separated from checks that must be performed on the actual MT5 terminal and broker demo account.</p></div>
      <Status good={Boolean(data && data.status === "ready" && data.manual_validation_required === 0)}>{data?.status?.replaceAll("_", " ").toUpperCase() ?? "LOADING"}</Status>
    </div>
    <div className="readiness-summary">
      <div><ShieldCheck size={18}/><b>{data ? `${data.automated_passed} / ${data.automated_total}` : "—"}</b><span>AUTOMATED GATES PASSED</span></div>
      <div><Clock3 size={18}/><b>{data?.manual_validation_required ?? "—"}</b><span>OPERATOR VALIDATIONS REQUIRED</span></div>
    </div>
    <div className="readiness-meta"><span><Clock3 size={13}/> Evidence updated {data ? new Date(data.updated_at).toLocaleString() : "Awaiting report"}</span><span>{data?.automated_gates.filter(item => item.status !== "passed").length ?? "—"} automated item(s) still outstanding</span></div>
    <h3>Automated checks <small>{data ? `${data.automated_passed} passed · ${data.automated_total - data.automated_passed} outstanding` : "Awaiting report"}</small></h3>
    <div className="readiness-list">{data?.automated_gates.map(item => <Gate key={item.key} item={item}/>)}</div>
    <h3>Required real-terminal validation <small>{data ? `${data.manual_validation_required} still require validation` : "Awaiting report"}</small></h3>
    <div className="readiness-list">{data?.manual_gates.map(item => <Gate key={item.key} item={item}/>)}</div>
    <div className="readiness-warning"><AlertTriangle size={17}/><span>Readiness is not permission to trade. Manual checks cannot be marked complete by this dashboard. Execution remains disabled and live trading is unsupported.</span></div>
  </section>;
}
