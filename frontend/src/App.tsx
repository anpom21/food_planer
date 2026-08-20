import { useEffect, useState } from "react";

// The walking-skeleton shell: it proves the React app can reach the FastAPI
// backend same-origin under /api. Real screens are built in later tickets.

type Health = { status: string };

export function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json() as Promise<Health>)
      .then(setHealth)
      .catch((e: unknown) => setError(String(e)));
  }, []);

  return (
    <main style={{ fontFamily: "system-ui", padding: "2rem" }}>
      <h1>Food Planner</h1>
      <p>
        Backend:{" "}
        {error
          ? `unreachable (${error})`
          : health
            ? health.status
            : "checking…"}
      </p>
    </main>
  );
}
