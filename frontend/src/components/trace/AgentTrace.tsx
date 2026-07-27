"use client";

import { AnimatePresence, motion } from "framer-motion";
import {
  Bus,
  CheckCircle2,
  CircleDot,
  Compass,
  ListOrdered,
  MessageSquareText,
  RadioTower,
  RefreshCw,
  Train,
  type LucideIcon,
} from "lucide-react";

import { Panel, PanelHeader } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

/**
 * The LangGraph node roster, in pipeline order.
 *
 * Keyed by the node names the backend emits, so an unrecognised node still
 * renders (with a fallback label) rather than vanishing from the trace.
 */
const NODES: Record<string, { label: string; blurb: string; icon: LucideIcon }> = {
  planner: { label: "Planner", blurb: "Parsing intent · finding routes", icon: Compass },
  bus_rag: { label: "Bus RAG", blurb: "Matching bus timetables", icon: Bus },
  train_rag: { label: "Train RAG", blurb: "Scraping live train schedules", icon: Train },
  ranker: { label: "Ranker", blurb: "Scoring against your deadline", icon: ListOrdered },
  uber: { label: "Ride-hailing", blurb: "Checking last-mile options", icon: CircleDot },
  monitor: { label: "Monitor", blurb: "Checking for disruptions", icon: RadioTower },
  replanner: { label: "Replanner", blurb: "Finding an alternative", icon: RefreshCw },
  responder: { label: "Responder", blurb: "Composing your answer", icon: MessageSquareText },
};

function nodeInfo(name: string) {
  return (
    NODES[name] ?? {
      label: name.replace(/_/g, " "),
      blurb: "Working",
      icon: CircleDot,
    }
  );
}

export interface AgentTraceProps {
  /** Nodes that have fired, in order. Repeats are meaningful — a replan loop. */
  trace: string[];
  /** Node currently running; null once the run finishes. */
  current?: string | null;
  /** True while the graph is executing — drives the pulse and "live" chip. */
  active?: boolean;
  disruptionLevel?: string | null;
  replanAttempts?: number;
  /** Rendered flat and expanded (live) vs. compact and collapsed (history). */
  variant?: "live" | "summary";
  className?: string;
}

export function AgentTrace({
  trace,
  current = null,
  active = false,
  disruptionLevel = null,
  replanAttempts = 0,
  variant = "live",
  className,
}: AgentTraceProps) {
  if (trace.length === 0 && !active) return null;

  // The trace is a run log, not a set: `monitor` appearing twice means the
  // graph looped through the replanner, and collapsing that would hide the
  // single most interesting thing the agent did. Each entry gets a key that
  // includes its position so repeats animate independently.
  const steps = trace.map((node, index) => ({
    key: `${node}-${index}`,
    node,
    index,
    isCurrent: active && index === trace.length - 1 && current === node,
  }));

  const looped = replanAttempts > 0;

  return (
    <Panel className={cn("p-4", className)}>
      <PanelHeader
        icon={<RadioTower className="size-3.5" />}
        title="Agent trace"
        meta={
          active ? (
            <span className="flex items-center gap-1.5 text-[11px] font-semibold text-signal-400">
              <span className="size-1.5 animate-pulse rounded-full bg-signal-400" />
              Live
            </span>
          ) : (
            <span className="text-[11px] font-medium text-ink-500">
              {trace.length} step{trace.length === 1 ? "" : "s"}
            </span>
          )
        }
      />

      <ol className={cn("mt-3", variant === "summary" ? "space-y-0.5" : "space-y-1")}>
        <AnimatePresence initial={false}>
          {steps.map(({ key, node, index, isCurrent }) => {
            const { label, blurb, icon: Icon } = nodeInfo(node);
            const done = !isCurrent;

            // A repeated node is the graph looping back after a disruption.
            const isRepeat = trace.indexOf(node) !== index;

            return (
              <motion.li
                key={key}
                layout
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.22, ease: [0.2, 0.9, 0.3, 1] }}
                className="relative flex items-start gap-3 pl-1"
              >
                {/* Rail connecting the markers, stopping short of the last one. */}
                {index < steps.length - 1 && (
                  <span
                    aria-hidden
                    className="absolute top-7 left-[15px] h-[calc(100%-1rem)] w-px bg-console-700"
                  />
                )}

                <span
                  className={cn(
                    "relative z-10 mt-0.5 grid size-7 shrink-0 place-items-center rounded-full border transition",
                    isCurrent
                      ? "animate-pulse-ring border-signal-500 bg-signal-500/15 text-signal-400"
                      : "border-console-600 bg-console-850 text-ink-500",
                    done && !isCurrent && "text-go-400 border-go-500/30",
                  )}
                >
                  {done && !isCurrent ? (
                    <CheckCircle2 className="size-3.5" />
                  ) : (
                    <Icon className="size-3.5" />
                  )}
                </span>

                <div className="min-w-0 flex-1 pb-1">
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        "text-sm font-medium capitalize",
                        isCurrent ? "text-signal-400" : "text-ink-100",
                      )}
                    >
                      {label}
                    </span>
                    {isRepeat && (
                      <span className="rounded bg-glow-400/10 px-1.5 py-px text-[10px] font-semibold text-glow-400">
                        retry
                      </span>
                    )}
                  </div>
                  {variant === "live" && (
                    <p className={cn("text-xs", isCurrent ? "text-ink-300" : "text-ink-500")}>
                      {isCurrent ? blurb : ""}
                    </p>
                  )}
                </div>
              </motion.li>
            );
          })}
        </AnimatePresence>
      </ol>

      {looped && (
        <p className="mt-3 border-t border-console-700/60 pt-2.5 text-xs text-glow-400">
          Replanned {replanAttempts} time{replanAttempts === 1 ? "" : "s"} after detecting a{" "}
          {disruptionLevel ?? "disruption"}.
        </p>
      )}
    </Panel>
  );
}
