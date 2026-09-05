/**
 * Cross-cutting components — FRONTEND.md Section 4.
 *
 * Built once and reused, as that section requires. Every one of these renders
 * colour AND text, never colour alone.
 */

import type { ReactNode } from "react";
import { humanise } from "../lib/format";

type Tone = "neutral" | "success" | "warning" | "error" | "accent";

/**
 * Status semantics, straight from FRONTEND.md Section 4.1. `negotiation` is
 * mapped to warning ("needs attention") and is deliberately NOT merged with
 * approved or pending_approval — Screen 3 requires it to read as its own
 * distinct state everywhere a status appears.
 */
const STATUS_TONE: Record<string, Tone> = {
  draft: "neutral",
  pending: "warning",
  pending_approval: "warning",
  under_negotiation: "warning",
  sent: "accent",
  backordered: "warning",
  partially_fulfilled: "warning",
  unpaid: "warning",
  approved: "success",
  confirmed: "success",
  active: "success",
  paid: "success",
  fulfilled: "success",
  rejected: "error",
  cancelled: "error",
  past_due: "error",
  returned_for_revision: "warning",
};

const RISK_TONE: Record<string, Tone> = {
  LOW: "success",
  MEDIUM: "warning",
  HIGH: "error",
};

export function StatusBadge({ status }: { status: string }) {
  const tone = STATUS_TONE[status] ?? "neutral";
  return <span className={`badge badge--${tone}`}>{humanise(status)}</span>;
}

export function RiskBadge({ band }: { band: string }) {
  return <span className={`badge badge--${RISK_TONE[band] ?? "neutral"}`}>{band}</span>;
}

export function OverLimitBadge({ over }: { over: boolean }) {
  return over ? (
    <span className="badge badge--error">OVER LIMIT</span>
  ) : (
    <span className="badge badge--success">OK</span>
  );
}

export function KpiCard({
  label,
  value,
  caption,
  onClick,
}: {
  label: string;
  value: ReactNode;
  caption?: string;
  onClick?: () => void;
}) {
  const content = (
    <>
      <div className="kpi__label">{label}</div>
      <div className="kpi__value">{value}</div>
      {caption && <div className="kpi__caption">{caption}</div>}
    </>
  );
  // Screen 2's cards are the entry point into filtered list views
  // (FRONTEND.md Section 4.2), so they are buttons when they navigate.
  return onClick ? (
    <button type="button" className="kpi" onClick={onClick}>
      {content}
    </button>
  ) : (
    <div className="kpi">{content}</div>
  );
}

/**
 * The persistent contextual help bar every wireframe screen carries
 * (Section 4.4). Inline and always present — not a toast, not a modal.
 */
export function NoteBar({
  children,
  tone = "info",
}: {
  children: ReactNode;
  tone?: "info" | "warning";
}) {
  return <div className={tone === "warning" ? "note note--warning" : "note"}>{children}</div>;
}

export function FilterChips({
  options,
  active,
  onChange,
}: {
  options: { value: string; label: string; count?: number }[];
  active: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="toolbar">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className={`chip ${option.value === active ? "chip--active" : ""}`}
          onClick={() => onChange(option.value)}
        >
          {option.count !== undefined ? `${option.count} ${option.label}` : option.label}
        </button>
      ))}
    </div>
  );
}

/** Section 4.5. `skipped` renders greyed with an explicit label (TBD #6). */
export function Stepper({
  steps,
}: {
  steps: { label: string; state: "done" | "current" | "upcoming" | "skipped" | "rejected"; hint?: string }[];
}) {
  return (
    <div className="stepper">
      {steps.map((step, index) => (
        <div key={step.label + index} style={{ display: "contents" }}>
          {index > 0 && <span className="step__arrow">→</span>}
          <span className={`step step--${step.state}`}>
            <span className="step__dot" />
            {step.label}
            {step.state === "skipped" && <span className="muted"> · not required</span>}
            {step.hint && <span className="muted"> · {step.hint}</span>}
          </span>
        </div>
      ))}
    </div>
  );
}

/* --- States (Section 7) --------------------------------------------------
 * Skeletons rather than a full-page spinner, and two distinct empty cases:
 * "nothing yet" versus "nothing matches your filter".
 */

export function TableSkeleton({ rows = 4, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <div className="table-wrap">
      <table className="data">
        <tbody>
          {Array.from({ length: rows }).map((_, r) => (
            <tr key={r}>
              {Array.from({ length: cols }).map((__, c) => (
                <td key={c}>
                  <div className="skeleton" style={{ width: c === 0 ? "60%" : "40%" }} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="card">
      <div className="empty">
        <div className="empty__title">{title}</div>
        {hint && <p>{hint}</p>}
        {action && <div style={{ marginTop: "var(--space-4)" }}>{action}</div>}
      </div>
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="card">
      <div className="error-state">
        <div className="error-state__title">Something went wrong</div>
        {/* The message is already generic by the time it reaches here: the
            backend never returns stack traces or SQL. */}
        <p>{message}</p>
        {onRetry && (
          <button type="button" className="btn" onClick={onRetry}>
            Try again
          </button>
        )}
      </div>
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="page-header">
      <div>
        <h1 className="page-title">{title}</h1>
        {subtitle && <p className="page-subtitle">{subtitle}</p>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </div>
  );
}
