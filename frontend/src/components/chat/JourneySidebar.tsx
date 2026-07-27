"use client";

import {
  CircleDot,
  Clock,
  Flag,
  MapPin,
  Plus,
  Sparkles,
  Target,
  TrainFront,
} from "lucide-react";

import { Badge, Button, Panel, PanelHeader } from "@/components/ui/primitives";
import type { JourneySummary } from "@/lib/types";
import { cn, LANGUAGE_NAMES, OPTIMISE_LABELS } from "@/lib/utils";

const EXAMPLES = [
  "I want to go to Kandy from Colombo at 7am",
  "What's the cheapest way to Galle?",
  "ට්‍රේන් එකෙන් කෑගල්ල ට යන්නේ කොහොමද?",
  "கண்டிக்கு எப்படி போவது?",
];

function Field({
  icon: Icon,
  label,
  value,
  accent = false,
}: {
  icon: typeof MapPin;
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <div className="flex items-center gap-2.5">
      <Icon className={cn("size-3.5 shrink-0", accent ? "text-signal-400" : "text-ink-700")} />
      <span className="eyebrow w-16 shrink-0">{label}</span>
      <span className="truncate text-xs font-medium text-ink-100">{value}</span>
    </div>
  );
}

export function JourneySidebar({
  journey,
  onNewJourney,
  onExample,
  disabled = false,
  className,
}: {
  journey: JourneySummary;
  onNewJourney: () => void;
  onExample: (text: string) => void;
  disabled?: boolean;
  className?: string;
}) {
  const hasJourney = Boolean(journey.origin || journey.destination);

  return (
    <aside className={cn("space-y-3", className)}>
      <Panel className="p-4">
        <PanelHeader
          icon={<TrainFront className="size-3.5" />}
          title="Current journey"
          meta={
            journey.language !== "en" ? (
              <Badge tone="signal">{LANGUAGE_NAMES[journey.language]}</Badge>
            ) : undefined
          }
        />

        {hasJourney ? (
          <div className="mt-3 space-y-2">
            <Field
              icon={CircleDot}
              label="From"
              value={journey.origin ?? "—"}
              accent={Boolean(journey.origin)}
            />
            <Field
              icon={Flag}
              label="To"
              value={journey.destination ?? "—"}
              accent={Boolean(journey.destination)}
            />
            {journey.requested_time && (
              <Field icon={Clock} label="Departs" value={journey.requested_time} />
            )}
            {journey.expected_arrival_time && (
              <Field icon={Flag} label="By" value={journey.expected_arrival_time} />
            )}
            {journey.preferred_mode && (
              <Field
                icon={TrainFront}
                label="Mode"
                value={journey.preferred_mode.replace(/^\w/, (c) => c.toUpperCase())}
              />
            )}
            {journey.optimise_for && (
              <Field
                icon={Target}
                label="Priority"
                value={OPTIMISE_LABELS[journey.optimise_for]}
                accent
              />
            )}
          </div>
        ) : (
          <p className="mt-3 text-xs text-ink-500">
            Tell me where you&apos;re going and I&apos;ll build the journey here as we talk.
          </p>
        )}

        <Button
          variant="subtle"
          size="sm"
          onClick={onNewJourney}
          disabled={disabled}
          className="mt-4 w-full"
        >
          <Plus className="size-3.5" />
          New journey
        </Button>
      </Panel>

      <Panel className="p-4">
        <PanelHeader icon={<Sparkles className="size-3.5" />} title="Try asking" />
        <div className="mt-3 space-y-1.5">
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => onExample(example)}
              disabled={disabled}
              className="w-full rounded-lg border border-console-700/70 bg-console-900/40 px-3 py-2 text-left text-[11px] text-ink-300 transition hover:border-signal-500/40 hover:text-signal-400 disabled:opacity-45"
            >
              {example}
            </button>
          ))}
        </div>
      </Panel>
    </aside>
  );
}
