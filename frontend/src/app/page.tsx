"use client";

import { TrainFront } from "lucide-react";
import { useEffect, useState } from "react";

import { ChatPanel } from "@/components/chat/ChatPanel";
import { Badge } from "@/components/ui/primitives";
import { fetchConfig } from "@/lib/api";

type Health = "checking" | "online" | "offline";

export default function Home() {
  // The Maps key comes from the backend rather than NEXT_PUBLIC_*, so the
  // whole app stays configured from one .env file at the repo root. It
  // doubles as a liveness probe: if this call fails the agent is unreachable,
  // and the header says so before the commuter types into the void.
  const [mapsKey, setMapsKey] = useState("");
  const [health, setHealth] = useState<Health>("checking");

  useEffect(() => {
    let cancelled = false;

    fetchConfig()
      .then((config) => {
        if (cancelled) return;
        setMapsKey(config.maps_browser_key);
        setHealth("online");
      })
      .catch(() => {
        if (!cancelled) setHealth("offline");
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const healthTone = health === "online" ? "go" : health === "offline" ? "alert" : "neutral";
  const healthDot =
    health === "online"
      ? "bg-go-400"
      : health === "offline"
        ? "bg-alert-400"
        : "animate-pulse bg-ink-500";

  return (
    <>
      <header className="sticky top-0 z-30 border-b border-console-700/50 bg-console-950/75 backdrop-blur-xl">
        <div className="mx-auto flex w-full max-w-7xl items-center gap-3 px-4 py-3">
          <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-signal-500/12 text-signal-400 ring-1 ring-signal-500/25">
            <TrainFront className="size-4" />
          </span>

          <div className="min-w-0 flex-1">
            <h1 className="text-sm font-semibold tracking-tight text-ink-100">CommuteAI</h1>
            <p className="truncate text-[11px] text-ink-500">
              Disruption-aware transit planning · Sri Lanka
            </p>
          </div>

          <Badge tone={healthTone}>
            <span className={`size-1.5 rounded-full ${healthDot}`} />
            {health === "online"
              ? "Agent online"
              : health === "offline"
                ? "Agent offline"
                : "Connecting"}
          </Badge>
        </div>

        {health === "offline" && (
          <div className="border-t border-alert-500/25 bg-alert-500/10 px-4 py-2 text-center text-[11px] text-alert-400">
            Can&apos;t reach the agent. Start the backend with{" "}
            <code className="rounded bg-alert-500/12 px-1 py-px">
              uv run uvicorn commute_agent.api.main:app --reload --port 8000
            </code>
          </div>
        )}
      </header>

      <main className="flex min-h-0 flex-1 flex-col pt-4">
        <ChatPanel mapsKey={mapsKey} />
      </main>
    </>
  );
}
