import { useEffect, useState } from "react";
import { fetchReadiness, type HealthResponse } from "./lib/api";

/**
 * PHASE 1 FOUNDATION PLACEHOLDER - NOT A DESIGNED SCREEN.
 *
 * PLAN.md Phase 8 (Section 13) holds all UI work until the Excalidraw mockup /
 * design-system resource is provided. This component exists only to prove the
 * React -> FastAPI -> PostgreSQL path is wired end to end. It is intentionally
 * unstyled: no palette, no component library, no layout decisions have been
 * invented here. Replace it entirely once design input arrives.
 */
export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchReadiness()
      .then(setHealth)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Request failed"));
  }, []);

  return (
    <main>
      <h1>DealFlow360</h1>
      <p>
        <strong>Phase 1 foundation placeholder.</strong> No UI has been designed yet - see
        PLAN.md Phase 8. This page only verifies backend connectivity.
      </p>

      <h2>Backend connectivity</h2>
      {error && <p>Backend unreachable: {error}</p>}
      {!error && !health && <p>Checking...</p>}
      {health && (
        <ul>
          <li>API status: {health.status}</li>
          <li>Environment: {health.environment}</li>
          <li>Database: {health.database}</li>
        </ul>
      )}
    </main>
  );
}
