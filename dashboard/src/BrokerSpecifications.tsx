import { useEffect, useState } from "react";
import { AlertTriangle, ShieldCheck } from "lucide-react";
import { getBrokerSpecifications, type BrokerSpecification } from "./api";

function number(value: number, digits = 5) {
  return Number.isFinite(value) ? value.toLocaleString("en-US", { maximumFractionDigits: digits }) : "—";
}

function age(value: number | null) {
  if (value == null) return "Unknown age";
  if (value < 60) return `${Math.round(value)}s ago`;
  if (value < 3600) return `${Math.round(value / 60)}m ago`;
  return `${(value / 3600).toFixed(1)}h ago`;
}

export default function BrokerSpecifications() {
  const [items, setItems] = useState<BrokerSpecification[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const result = await getBrokerSpecifications();
        if (active) {
          setItems(result.items ?? []);
          setError("");
        }
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : String(cause));
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 30000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  return <section className="panel">
    <div className="section-head">
      <div><div className="eyebrow">BROKER CONTRACT METADATA</div><h2>Symbol specifications</h2>
        <p className="subhead">Broker-reported trading constraints used by preflight and risk calculations. Read-only reference; no orders can be submitted here.</p>
      </div>
      <span className="research-tag"><ShieldCheck size={13}/> READ ONLY</span>
    </div>
    {error && <div className="alert-row"><AlertTriangle size={16}/><span>Specifications could not refresh: {error}</span></div>}
    <div className="table-wrap"><table><thead><tr>
      <th>SYMBOL</th><th>STATUS</th><th>VOLUME MIN / STEP / MAX</th><th>CONTRACT</th>
      <th>TICK SIZE</th><th>TICK VALUE LOSS</th><th>STOPS / FREEZE</th><th>CURRENCIES</th><th>OBSERVED</th>
    </tr></thead><tbody>
      {items.map(item => <tr key={item.symbol}>
        <td className="symbol">{item.symbol}</td>
        <td><span className={`signal ${item.fresh && item.trade_allowed ? "buy" : "sell"}`}>{!item.fresh ? "STALE" : item.trade_allowed ? "ALLOWED" : "DISABLED"}</span></td>
        <td>{number(item.volume_min, 3)} / {number(item.volume_step, 3)} / {number(item.volume_max, 3)}</td>
        <td>{number(item.contract_size, 2)}</td>
        <td>{number(item.tick_size, 8)}</td>
        <td>{number(item.tick_value_loss, 5)} {item.account_currency}</td>
        <td>{item.stops_level_points} / {item.freeze_level_points} pts</td>
        <td>{item.base_currency}/{item.profit_currency} · margin {item.margin_currency}</td>
        <td>{age(item.age_seconds)}</td>
      </tr>)}
      {!items.length && <tr><td colSpan={9} className="empty">No broker specifications received yet. The read-only MT5 telemetry EA must report symbol metadata first.</td></tr>}
    </tbody></table></div>
    <p className="subhead">A stale or missing specification must not be treated as permission to trade. Broker rules can change; the execution preflight remains authoritative.</p>
  </section>;
}
