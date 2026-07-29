"use client";

import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import { Panel, PanelHeader } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

export interface CollapsibleSectionProps {
  icon?: ReactNode;
  title: string;
  /**
   * Shown beside the chevron in both states. This is what survives collapsing,
   * so it should carry whatever the commuter would otherwise have to expand
   * the section to learn — a count, a warning, the one number that matters.
   */
  meta?: ReactNode;
  defaultOpen?: boolean;
  /** Applied to the body wrapper: padding and the divider under the header. */
  bodyClassName?: string;
  className?: string;
  children: ReactNode;
}

/**
 * A panel whose detail is folded away behind its own header.
 *
 * Secondary detail stays one click from the answer rather than stacked on top
 * of it. Collapsed is the default because a chat turn already leads with the
 * route the commuter asked for; everything here is the reasoning behind it.
 *
 * The body unmounts while closed, which is what keeps a long transcript cheap
 * to scroll — so nothing inside may hold state the commuter would miss losing.
 */
export function CollapsibleSection({
  icon,
  title,
  meta,
  defaultOpen = false,
  bodyClassName,
  className,
  children,
}: CollapsibleSectionProps) {
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = useId();

  return (
    <Panel className={cn("overflow-hidden", className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={bodyId}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition hover:bg-console-800/50"
      >
        <PanelHeader icon={icon} title={title} />
        <span className="flex items-center gap-2 text-[11px] font-medium text-ink-500">
          {meta}
          <ChevronDown className={cn("size-4 shrink-0 transition-transform", open && "rotate-180")} />
        </span>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            id={bodyId}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.24, ease: [0.2, 0.9, 0.3, 1] }}
            className="overflow-hidden"
          >
            <div className={bodyClassName}>{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </Panel>
  );
}
