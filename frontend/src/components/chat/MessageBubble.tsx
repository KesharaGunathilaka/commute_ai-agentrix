"use client";

import { motion } from "framer-motion";
import { AlertCircle, Languages, Loader2, Train, Volume2, VolumeX } from "lucide-react";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { BookingCard } from "@/components/journey/BookingCard";
import { JourneyPlan } from "@/components/journey/JourneyPlan";
import { Button } from "@/components/ui/primitives";
import type { ChatMessage } from "@/lib/types";
import { cn, LANGUAGE_NAMES } from "@/lib/utils";

export interface MessageBubbleProps {
  message: ChatMessage;
  mapsKey: string;
  onReadAloud: (id: string, text: string, lang: string) => void;
  isLoadingAudio: boolean;
  isPlayingAudio: boolean;
}

export function MessageBubble({
  message,
  mapsKey,
  onReadAloud,
  isLoadingAudio,
  isPlayingAudio,
}: MessageBubbleProps) {
  const [showTranslation, setShowTranslation] = useState(false);
  const isUser = message.role === "user";

  if (isUser) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2 }}
        className="flex justify-end"
      >
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-signal-500/12 px-4 py-2.5 text-sm text-ink-100 ring-1 ring-signal-500/25">
          {message.text}
        </div>
      </motion.div>
    );
  }

  // Read-aloud always speaks English: the gTTS voices for Sinhala and Tamil
  // are markedly worse, and the English gloss is always present.
  const spokenText = message.textEn || message.text;
  const language = message.language ?? "en";
  const hasTranslation = language !== "en" && Boolean(message.textEn) && message.textEn !== message.text;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="space-y-3"
    >
      <div className="flex gap-3">
        <span
          className={cn(
            "mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg",
            message.error
              ? "bg-alert-500/12 text-alert-400"
              : "bg-signal-500/12 text-signal-400",
          )}
        >
          {message.error ? <AlertCircle className="size-3.5" /> : <Train className="size-3.5" />}
        </span>

        <div className="min-w-0 flex-1">
          <div
            className={cn(
              "rounded-2xl rounded-tl-md px-4 py-2.5 text-sm ring-1",
              message.error
                ? "bg-alert-500/8 text-alert-400 ring-alert-500/25"
                : "bg-console-850/80 text-ink-300 ring-console-700/70",
            )}
          >
            <div className="md">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.text}</ReactMarkdown>
            </div>
          </div>

          <div className="mt-1.5 flex flex-wrap items-center gap-1">
            {!message.error && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onReadAloud(message.id, spokenText, "en")}
                aria-label={isPlayingAudio ? "Stop reading" : "Read this message aloud"}
                className="h-7 px-2 text-[11px]"
              >
                {isLoadingAudio ? (
                  <Loader2 className="size-3 animate-spin" />
                ) : isPlayingAudio ? (
                  <VolumeX className="size-3" />
                ) : (
                  <Volume2 className="size-3" />
                )}
                {isPlayingAudio ? "Stop" : "Read aloud"}
              </Button>
            )}

            {hasTranslation && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setShowTranslation((v) => !v)}
                aria-expanded={showTranslation}
                className="h-7 px-2 text-[11px]"
              >
                <Languages className="size-3" />
                {showTranslation ? "Hide English" : "English"}
              </Button>
            )}

            {language !== "en" && (
              <span className="ml-auto text-[10px] text-ink-700">
                {LANGUAGE_NAMES[language]}
              </span>
            )}
          </div>

          {showTranslation && message.textEn && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              className="md mt-1.5 overflow-hidden rounded-xl border border-console-700/60 bg-console-900/50 px-3 py-2 text-xs text-ink-500"
            >
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.textEn}</ReactMarkdown>
            </motion.div>
          )}
        </div>
      </div>

      {/* A booking turn reads top to bottom as the journey now stands: the
          booked ride leg first, then the plan for what follows it. */}
      {(message.booking || message.state) && (
        <div className="space-y-3 pl-10">
          {message.booking && (
            <BookingCard booking={message.booking} replanFrom={message.replanFrom} />
          )}
          {message.state && <JourneyPlan state={message.state} mapsKey={mapsKey} />}
        </div>
      )}
    </motion.div>
  );
}
