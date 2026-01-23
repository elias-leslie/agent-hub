"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";

export function Tooltip({
  children,
  content,
  position = "top",
}: {
  children: React.ReactNode;
  content: React.ReactNode;
  position?: "top" | "bottom";
}) {
  const [show, setShow] = useState(false);

  return (
    <div
      className="relative inline-flex"
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      {children}
      {show && (
        <div
          className={cn(
            "absolute z-50 px-2 py-1 text-[10px] font-medium whitespace-nowrap rounded shadow-lg",
            "bg-slate-900 text-white dark:bg-white dark:text-slate-900",
            "animate-in fade-in-0 zoom-in-95 duration-150",
            position === "top"
              ? "bottom-full mb-1.5 left-1/2 -translate-x-1/2"
              : "top-full mt-1.5 left-1/2 -translate-x-1/2"
          )}
        >
          {content}
        </div>
      )}
    </div>
  );
}
