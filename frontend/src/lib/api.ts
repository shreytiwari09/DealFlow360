/**
 * Thin API client.
 *
 * The base URL comes from VITE_API_BASE_URL so the frontend is never built
 * with a hardcoded host. Nothing secret is ever placed in this bundle -
 * SECURITY_SPEC.md Section 7: anything sent to the browser is public.
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export interface HealthResponse {
  status: "ok" | "degraded";
  environment: string;
  database: "ok" | "unavailable" | "not_checked";
}

export async function fetchReadiness(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/health/ready`);
  // 503 still carries a valid HealthResponse body, so it is not an error here.
  if (!response.ok && response.status !== 503) {
    throw new Error(`Unexpected response: ${response.status}`);
  }
  return (await response.json()) as HealthResponse;
}
