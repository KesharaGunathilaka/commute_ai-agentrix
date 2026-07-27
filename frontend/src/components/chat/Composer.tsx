"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Mic, MicOff, SendHorizontal, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/primitives";
import { useSpeechInput } from "@/hooks/useSpeechInput";
import type { ClarificationField, Language } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Placeholder tuned to whatever the agent just asked for. */
const PROMPTS: Record<ClarificationField | "default", string> = {
  default: "Ask about your journey…",
  both: "e.g. Colombo Fort to Kandy",
  origin: "Which station are you leaving from?",
  destination: "Where are you heading?",
  time: "e.g. 07:30 — or 'now'",
  arrival: "e.g. by 10:00 — or 'no'",
};

export interface ComposerProps {
  onSend: (text: string) => void;
  disabled?: boolean;
  /** Drives the placeholder and the quick-reply chips. */
  awaiting?: ClarificationField | null;
  language?: Language;
}

export function Composer({ onSend, disabled = false, awaiting, language = "en" }: ComposerProps) {
  const [value, setValue] = useState("");
  const textarea = useRef<HTMLTextAreaElement>(null);

  // Dictation appends rather than replaces — the recogniser fires once per
  // phrase, so a speaker who pauses mid-sentence would otherwise lose the
  // first half.
  const handleTranscript = useCallback((transcript: string) => {
    setValue((prev) => (prev ? `${prev.trimEnd()} ${transcript}` : transcript));
  }, []);

  const speech = useSpeechInput(handleTranscript);

  // Grow the textarea with its content, up to a ceiling.
  useEffect(() => {
    const el = textarea.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [value]);

  const submit = useCallback(() => {
    const text = value.trim();
    if (!text || disabled) return;
    if (speech.listening) speech.stop();
    onSend(text);
    setValue("");
  }, [value, disabled, onSend, speech]);

  const quickReplies =
    awaiting === "time"
      ? ["Now", "07:30", "08:00"]
      : awaiting === "arrival"
        ? ["No deadline", "By 10:00"]
        : [];

  return (
    <div className="space-y-2">
      {/* Voice errors are transient and self-explanatory — dismissible, not modal. */}
      <AnimatePresence>
        {speech.error && (
          <motion.div
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 4 }}
            className="flex items-center gap-2 rounded-lg border border-alert-500/35 bg-alert-500/10 px-3 py-1.5 text-[11px] text-alert-400"
          >
            <MicOff className="size-3 shrink-0" />
            <span className="flex-1">{speech.error}</span>
            <button type="button" onClick={speech.clearError} aria-label="Dismiss">
              <X className="size-3" />
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {quickReplies.length > 0 && !disabled && (
        <div className="flex flex-wrap gap-1.5">
          {quickReplies.map((reply) => (
            <button
              key={reply}
              type="button"
              onClick={() => onSend(reply)}
              className="rounded-full border border-console-700 bg-console-800/60 px-3 py-1 text-[11px] text-ink-300 transition hover:border-signal-500/45 hover:text-signal-400"
            >
              {reply}
            </button>
          ))}
        </div>
      )}

      <div
        className={cn(
          "panel flex items-end gap-2 p-2 transition",
          speech.listening && "border-signal-500/50",
        )}
      >
        <textarea
          ref={textarea}
          rows={1}
          value={speech.interim ? `${value} ${speech.interim}`.trim() : value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            // Enter sends; Shift+Enter breaks the line.
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          disabled={disabled}
          placeholder={PROMPTS[awaiting ?? "default"]}
          aria-label="Message"
          className="max-h-40 flex-1 resize-none bg-transparent px-2 py-2 text-sm text-ink-100 placeholder:text-ink-700 focus:outline-none disabled:opacity-50"
        />

        {speech.supported && (
          <Button
            variant={speech.listening ? "primary" : "ghost"}
            size="icon"
            onClick={() => (speech.listening ? speech.stop() : speech.start(language))}
            disabled={disabled}
            aria-label={speech.listening ? "Stop dictation" : "Dictate your message"}
            className={cn(speech.listening && "animate-pulse-ring")}
          >
            <Mic className="size-4" />
          </Button>
        )}

        <Button
          variant="primary"
          size="icon"
          onClick={submit}
          disabled={disabled || !value.trim()}
          aria-label="Send message"
        >
          <SendHorizontal className="size-4" />
        </Button>
      </div>

      <p className="px-1 text-[10px] text-ink-700">
        {speech.listening
          ? "Listening — speak now."
          : "Ask in English, Sinhala, or Tamil. Enter to send, Shift+Enter for a new line."}
      </p>
    </div>
  );
}
