/** Display formatting. Amounts arrive as strings so no precision is lost. */

export function money(amount: string | number, currency = "INR"): string {
  const value = typeof amount === "string" ? Number(amount) : amount;
  if (!Number.isFinite(value)) return "—";
  try {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    }).format(value);
  } catch {
    return `${currency} ${value.toFixed(2)}`;
  }
}

export function percent(value: string | number, places = 2): string {
  const num = typeof value === "string" ? Number(value) : value;
  return Number.isFinite(num) ? `${num.toFixed(places)}%` : "—";
}

export function points(value: string | number): string {
  const num = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(num) || num === 0) return "0 pt";
  return `${num.toFixed(2)} pt`;
}

export function dateTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? "—"
    : d.toLocaleString(undefined, {
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      });
}

/** draft -> Draft, pending_approval -> Pending Approval */
export function humanise(value: string): string {
  return value
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}
