"use client";

import { useState, useEffect, useRef } from "react";
import { FolderOpen, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ProjectConfig } from "@/app/chat/hooks/useProjectContext";

interface ProjectDropdownProps {
  projects: ProjectConfig[];
  selectedProject: ProjectConfig;
  onSelectProject: (project: ProjectConfig) => void;
}

export function ProjectDropdown({
  projects,
  selectedProject,
  onSelectProject,
}: ProjectDropdownProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleMouseDown(e: MouseEvent) {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleMouseDown);
    return () => document.removeEventListener("mousedown", handleMouseDown);
  }, []);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape" && isOpen) {
        setIsOpen(false);
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen]);

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={cn(
          "flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium",
          "bg-indigo-50 dark:bg-indigo-900/20 text-indigo-700 dark:text-indigo-400",
          "hover:bg-indigo-100 dark:hover:bg-indigo-900/40 transition-colors"
        )}
      >
        <FolderOpen className="h-3.5 w-3.5" />
        {selectedProject.name}
        <ChevronDown
          className={cn(
            "h-3 w-3 transition-transform",
            isOpen && "rotate-180"
          )}
        />
      </button>

      {isOpen && (
        <div className="absolute left-0 top-full mt-1 w-48 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 shadow-lg z-50">
          <div className="p-1">
            {projects.map((project) => (
              <button
                key={project.id}
                onClick={() => {
                  onSelectProject(project);
                  setIsOpen(false);
                }}
                className={cn(
                  "w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm text-left",
                  "hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors",
                  project.id === selectedProject.id &&
                    "bg-indigo-50 dark:bg-indigo-900/20 text-indigo-700 dark:text-indigo-400"
                )}
              >
                <FolderOpen className="h-4 w-4 flex-shrink-0" />
                <span className="flex-1">{project.name}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
