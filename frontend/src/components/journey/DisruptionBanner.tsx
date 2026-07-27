"use client";

import { motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, Ban, Clock } from "lucide-react";

import type { DisruptionStatus } from "@/lib/types";
import { cn, disruptionLevel } from "@/lib/utils";

export interface DisruptionBannerProps {
  status?: DisruptionStatus | null;
  /** How many times the agent replanned — shown as evidence it recovered. */
  replanAttempts?: number;
  /** Set when the run began with a disruption that was later routed around. */
  resolved?: boolean;
  className?: string;
}

/**
 * Live disruption state for the planned journey.
 *
 * Renders nothing when the feed is clear and nothing went wrong — a green
 * "all fine" bar on every single journey trains people to ignore the strip
 * entirely, which is exactly the strip you need them to read on the day it
 * turns red.
 */
export function DisruptionBanner({
  status,
  replanAttempts = 0,
  resolved = false,
  className,
}: DisruptionBannerProps) {
  const level = disruptionLevel(status);
  const record = status?.disruption;

  if (level === "clear" && !resolved) return null;

  // A run that hit a disruption and then found a clear alternative is good
  // news, and reads as such — distinct from both "all clear" and "disrupted".
  const tone = resolved && level === "clear" ? "resolved" : level;

  const config = {
    resolved: {
      Icon: CheckCircle2,
      wrap: "border-go-500/35 bg-go-500/10",
      accent: "text-go-400",
      title: "Disruption avoided",
    },
    delayed: {
      Icon: Clock,
      wrap: "border-glow-400/40 bg-glow-400/10",
      accent: "text-glow-400",
      title: "Delay reported",
    },
    cancelled: {
      Icon: Ban,
      wrap: "border-alert-500/45 bg-alert-500/10",
      accent: "text-alert-400",
      title: "Service cancelled",
    },
    clear: {
      Icon: AlertTriangle,
      wrap: "border-console-600 bg-console-800/60",
      accent: "text-ink-300",
      title: "Service notice",
    },
  }[tone];

  const { Icon } = config;

  return (
    <motion.div
      initial={{ opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      role="status"
      className={cn("flex gap-3 rounded-console border px-4 py-3", config.wrap, className)}
    >
      <Icon className={cn("mt-0.5 size-4 shrink-0", config.accent)} />

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <p className={cn("text-sm font-semibold", config.accent)}>{config.title}</p>
          {record?.delay_minutes ? (
            <span className="tabular rounded bg-alert-500/15 px-1.5 py-px text-[11px] font-semibold text-alert-400">
              +{record.delay_minutes} min
            </span>
          ) : null}
          {record?.affected_segment && (
            <span className="truncate text-[11px] text-ink-500">{record.affected_segment}</span>
          )}
        </div>

        {record?.message && <p className="mt-1 text-xs text-ink-300">{record.message}</p>}

        {replanAttempts > 0 && (
          <p className="mt-1.5 text-[11px] text-ink-500">
            The agent replanned {replanAttempts} time{replanAttempts === 1 ? "" : "s"} and
            {resolved ? " found a clear route." : " could not find a clear route."}
          </p>
        )}
      </div>
    </motion.div>
  );
}
