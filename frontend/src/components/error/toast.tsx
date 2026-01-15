"use client";

import {
  createContext,
  useContext,
  useCallback,
  useState,
  useEffect,
  type ReactNode,
} from "react";
import { CheckCircle, AlertCircle, AlertTriangle, Info, X } from "lucide-react";
import { cn } from "@/lib/utils";

type ToastType = "success" | "error" | "warning" | "info";

interface Toast {
  id: string;
  type: ToastType;
  title: string;
  message?: string;
  duration?: number;
  action?: {
    label: string;
    onClick: () => void;
  };
}

interface ToastContextValue {
  toasts: Toast[];
  addToast: (toast: Omit<Toast, "id">) => string;
  removeToast: (id: string) => void;
  clearToasts: () => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error("useToast must be used within a ToastProvider");
  }
  return context;
}

// Convenience methods
export function useToastActions() {
  const { addToast } = useToast();

  return {
    success: (title: string, message?: string) =>
      addToast({ type: "success", title, message }),
    error: (title: string, message?: string) =>
      addToast({ type: "error", title, message, duration: 8000 }),
    warning: (title: string, message?: string) =>
      addToast({ type: "warning", title, message, duration: 6000 }),
    info: (title: string, message?: string) =>
      addToast({ type: "info", title, message }),
  };
}

interface ToastProviderProps {
  children: ReactNode;
  position?: "top-right" | "top-left" | "bottom-right" | "bottom-left";
  maxToasts?: number;
}

export function ToastProvider({
  children,
  position = "bottom-right",
  maxToasts = 5,
}: ToastProviderProps) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = useCallback(
    (toast: Omit<Toast, "id">) => {
      const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      const newToast: Toast = {
        ...toast,
        id,
        duration: toast.duration ?? 4000,
      };

      setToasts((prev) => {
        const updated = [newToast, ...prev];
        return updated.slice(0, maxToasts);
      });

      return id;
    },
    [maxToasts],
  );

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const clearToasts = useCallback(() => {
    setToasts([]);
  }, []);

  const positionClasses = {
    "top-right": "top-4 right-4",
    "top-left": "top-4 left-4",
    "bottom-right": "bottom-4 right-4",
    "bottom-left": "bottom-4 left-4",
  };

  return (
    <ToastContext.Provider
      value={{ toasts, addToast, removeToast, clearToasts }}
    >
      {children}
      {/* Toast container */}
      <div
        className={cn(
          "fixed z-50 flex flex-col gap-2 max-w-sm w-full pointer-events-none",
          positionClasses[position],
        )}
        role="region"
        aria-label="Notifications"
      >
        {toasts.map((toast) => (
          <ToastItem
            key={toast.id}
            toast={toast}
            onDismiss={() => removeToast(toast.id)}
          />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

interface ToastItemProps {
  toast: Toast;
  onDismiss: () => void;
}

const TOAST_ICONS: Record<ToastType, typeof AlertCircle> = {
  success: CheckCircle,
  error: AlertCircle,
  warning: AlertTriangle,
  info: Info,
};

function ToastItem({ toast, onDismiss }: ToastItemProps) {
  const [isVisible, setIsVisible] = useState(false);
  const [isLeaving, setIsLeaving] = useState(false);
  const Icon = TOAST_ICONS[toast.type];

  // Enter animation
  useEffect(() => {
    const timer = setTimeout(() => setIsVisible(true), 10);
    return () => clearTimeout(timer);
  }, []);

  // Auto dismiss
  useEffect(() => {
    if (!toast.duration) return;

    const timer = setTimeout(() => {
      handleDismiss();
    }, toast.duration);

    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [toast.duration]);

  const handleDismiss = () => {
    setIsLeaving(true);
    setTimeout(onDismiss, 200);
  };

  const typeStyles = {
    success: {
      bg: "bg-emerald-50 dark:bg-emerald-950/80",
      border: "border-emerald-200 dark:border-emerald-800",
      icon: "text-emerald-500 dark:text-emerald-400",
      title: "text-emerald-900 dark:text-emerald-100",
      message: "text-emerald-700 dark:text-emerald-300",
    },
    error: {
      bg: "bg-rose-50 dark:bg-rose-950/80",
      border: "border-rose-200 dark:border-rose-800",
      icon: "text-rose-500 dark:text-rose-400",
      title: "text-rose-900 dark:text-rose-100",
      message: "text-rose-700 dark:text-rose-300",
    },
    warning: {
      bg: "bg-amber-50 dark:bg-amber-950/80",
      border: "border-amber-200 dark:border-amber-800",
      icon: "text-amber-500 dark:text-amber-400",
      title: "text-amber-900 dark:text-amber-100",
      message: "text-amber-700 dark:text-amber-300",
    },
    info: {
      bg: "bg-sky-50 dark:bg-sky-950/80",
      border: "border-sky-200 dark:border-sky-800",
      icon: "text-sky-500 dark:text-sky-400",
      title: "text-sky-900 dark:text-sky-100",
      message: "text-sky-700 dark:text-sky-300",
    },
  };

  const styles = typeStyles[toast.type];

  return (
    <div
      role="alert"
      className={cn(
        "pointer-events-auto rounded-xl border shadow-lg backdrop-blur-sm",
        "transform transition-all duration-200 ease-out",
        styles.bg,
        styles.border,
        isVisible && !isLeaving
          ? "translate-x-0 opacity-100"
          : "translate-x-4 opacity-0",
      )}
    >
      <div className="flex items-start gap-3 p-4">
        <Icon className={cn("h-5 w-5 flex-shrink-0 mt-0.5", styles.icon)} />

        <div className="flex-1 min-w-0">
          <p className={cn("font-medium text-sm", styles.title)}>
            {toast.title}
          </p>
          {toast.message && (
            <p className={cn("text-sm mt-0.5", styles.message)}>
              {toast.message}
            </p>
          )}

          {toast.action && (
            <button
              onClick={() => {
                toast.action!.onClick();
                handleDismiss();
              }}
              className={cn(
                "mt-2 text-sm font-medium underline underline-offset-2",
                styles.icon,
              )}
            >
              {toast.action.label}
            </button>
          )}
        </div>

        <button
          onClick={handleDismiss}
          className={cn(
            "p-1 rounded-md transition-colors flex-shrink-0",
            "hover:bg-current/10",
            styles.icon,
          )}
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Progress bar for auto-dismiss */}
      {toast.duration && (
        <div className="h-1 w-full overflow-hidden rounded-b-xl">
          <div
            className={cn(
              "h-full transition-all ease-linear",
              toast.type === "success" && "bg-emerald-400 dark:bg-emerald-500",
              toast.type === "error" && "bg-rose-400 dark:bg-rose-500",
              toast.type === "warning" && "bg-amber-400 dark:bg-amber-500",
              toast.type === "info" && "bg-sky-400 dark:bg-sky-500",
            )}
            style={{
              width: isVisible ? "0%" : "100%",
              transitionDuration: `${toast.duration}ms`,
            }}
          />
        </div>
      )}
    </div>
  );
}
