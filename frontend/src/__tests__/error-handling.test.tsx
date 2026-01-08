import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import {
  ErrorMessage,
  RetryButton,
  RetryCountdownButton,
  ToastProvider,
  useToast,
  FullScreenError,
  ConnectionLostOverlay,
  ModelSwitcher,
  QuickModelSwitch,
  createAppError,
  type AppError,
} from "@/components/error";

// Test error
const testError: AppError = {
  id: "test-error-1",
  type: "rate_limit",
  severity: "warning",
  title: "Rate Limit Reached",
  message: "You've exceeded the rate limit. Please wait before retrying.",
  details: "Error code: 429\nRetry-After: 30",
  timestamp: new Date(),
  retryable: true,
  modelSpecific: true,
  suggestedActions: [
    { id: "wait", label: "Wait & Retry", action: "retry", primary: true },
    { id: "switch", label: "Try Different Model", action: "switch_model" },
  ],
};

const criticalError: AppError = {
  id: "test-error-2",
  type: "unknown",
  severity: "critical",
  title: "Something Went Wrong",
  message: "An unexpected error occurred. Please try again.",
  timestamp: new Date(),
  retryable: true,
  modelSpecific: false,
  suggestedActions: [
    { id: "retry", label: "Try Again", action: "retry", primary: true },
  ],
};

describe("createAppError", () => {
  it("creates error with correct type configuration", () => {
    const error = createAppError("rate_limit", "Rate limit exceeded");
    expect(error.type).toBe("rate_limit");
    expect(error.severity).toBe("warning");
    expect(error.title).toBe("Rate Limit Reached");
    expect(error.retryable).toBe(true);
    expect(error.modelSpecific).toBe(true);
  });

  it("includes custom message and details", () => {
    const error = createAppError("provider_down", "Service unavailable", "503");
    expect(error.message).toBe("Service unavailable");
    expect(error.details).toBe("503");
  });

  it("generates unique IDs", () => {
    const error1 = createAppError("network", "Connection failed");
    const error2 = createAppError("network", "Connection failed");
    expect(error1.id).not.toBe(error2.id);
  });
});

describe("ErrorMessage", () => {
  const onRetry = vi.fn();
  const onSwitchModel = vi.fn();
  const onDismiss = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders error title and message", () => {
    render(<ErrorMessage error={testError} />);
    expect(screen.getByText("Rate Limit Reached")).toBeInTheDocument();
    expect(
      screen.getByText(/You've exceeded the rate limit/)
    ).toBeInTheDocument();
  });

  it("shows suggested actions", () => {
    render(<ErrorMessage error={testError} onRetry={onRetry} />);
    // RetryButton renders with "Retry" label, other actions use their label
    expect(screen.getByText("Retry")).toBeInTheDocument();
    expect(screen.getByText("Try Different Model")).toBeInTheDocument();
  });

  it("calls onRetry when retry action is clicked", () => {
    render(<ErrorMessage error={testError} onRetry={onRetry} />);
    // Find the Retry button (RetryButton renders "Retry" text)
    const retryButton = screen.getByRole("button", { name: /retry/i });
    fireEvent.click(retryButton);
    expect(onRetry).toHaveBeenCalled();
  });

  it("calls onSwitchModel when switch model action is clicked", () => {
    render(
      <ErrorMessage error={testError} onSwitchModel={onSwitchModel} />
    );
    fireEvent.click(screen.getByText("Try Different Model"));
    expect(onSwitchModel).toHaveBeenCalled();
  });

  it("toggles details visibility", () => {
    render(<ErrorMessage error={testError} />);

    // Details should be hidden initially
    expect(screen.queryByText("Error code: 429")).not.toBeInTheDocument();

    // Click to show details
    fireEvent.click(screen.getByText("Show details"));
    expect(screen.getByText(/Error code: 429/)).toBeInTheDocument();

    // Click to hide details
    fireEvent.click(screen.getByText("Hide details"));
    expect(screen.queryByText("Error code: 429")).not.toBeInTheDocument();
  });

  it("renders compact variant", () => {
    render(<ErrorMessage error={testError} compact onRetry={onRetry} />);
    // Compact version shows truncated message
    expect(screen.getByText(/You've exceeded/)).toBeInTheDocument();
  });

  it("shows dismiss button when onDismiss provided", () => {
    render(<ErrorMessage error={testError} onDismiss={onDismiss} />);
    const dismissButtons = screen.getAllByRole("button");
    const dismissButton = dismissButtons.find(
      (btn) => btn.querySelector("svg")?.classList.contains("lucide-x")
    );
    expect(dismissButton).toBeTruthy();
  });
});

describe("RetryButton", () => {
  const onClick = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders with default label", () => {
    render(<RetryButton onClick={onClick} />);
    expect(screen.getByText("Retry")).toBeInTheDocument();
  });

  it("renders with custom label", () => {
    render(<RetryButton onClick={onClick} label="Try Again" />);
    expect(screen.getByText("Try Again")).toBeInTheDocument();
  });

  it("calls onClick when clicked", async () => {
    render(<RetryButton onClick={onClick} />);
    fireEvent.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalled();
  });

  it("shows loading state when clicked", async () => {
    render(<RetryButton onClick={() => new Promise((r) => setTimeout(r, 100))} />);
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText("Retrying...")).toBeInTheDocument();
  });

  it("is disabled when disabled prop is true", () => {
    render(<RetryButton onClick={onClick} disabled />);
    expect(screen.getByRole("button")).toBeDisabled();
  });

  it("applies variant classes", () => {
    const { rerender } = render(<RetryButton onClick={onClick} variant="warning" />);
    expect(screen.getByRole("button")).toHaveClass("bg-amber-600");

    rerender(<RetryButton onClick={onClick} variant="error" />);
    expect(screen.getByRole("button")).toHaveClass("bg-rose-600");
  });
});

describe("FullScreenError", () => {
  const onRetry = vi.fn();
  const onGoHome = vi.fn();
  const onContactSupport = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders error title and message", () => {
    render(<FullScreenError error={criticalError} />);
    expect(screen.getByText("Something Went Wrong")).toBeInTheDocument();
    expect(
      screen.getByText("An unexpected error occurred. Please try again.")
    ).toBeInTheDocument();
  });

  it("shows Try Again button for retryable errors", () => {
    render(<FullScreenError error={criticalError} onRetry={onRetry} />);
    expect(screen.getByText("Try Again")).toBeInTheDocument();
  });

  it("calls onRetry when Try Again is clicked", () => {
    render(<FullScreenError error={criticalError} onRetry={onRetry} />);
    fireEvent.click(screen.getByText("Try Again"));
    expect(onRetry).toHaveBeenCalled();
  });

  it("shows Go Home button when onGoHome provided", () => {
    render(<FullScreenError error={criticalError} onGoHome={onGoHome} />);
    expect(screen.getByText("Go Home")).toBeInTheDocument();
  });

  it("shows Contact Support when onContactSupport provided", () => {
    render(
      <FullScreenError error={criticalError} onContactSupport={onContactSupport} />
    );
    expect(screen.getByText("Contact Support")).toBeInTheDocument();
  });

  it("toggles technical details", () => {
    const errorWithDetails = {
      ...criticalError,
      details: "Stack trace here",
    };
    render(<FullScreenError error={errorWithDetails} />);

    // Click to expand
    fireEvent.click(screen.getByText("Technical Details"));
    expect(screen.getByText("Stack trace here")).toBeInTheDocument();
  });
});

describe("ConnectionLostOverlay", () => {
  const onRetry = vi.fn();

  it("renders connection lost message", () => {
    render(<ConnectionLostOverlay onRetry={onRetry} />);
    expect(screen.getByText("Connection Lost")).toBeInTheDocument();
  });

  it("shows retrying state", () => {
    render(<ConnectionLostOverlay onRetry={onRetry} isRetrying />);
    expect(screen.getByText("Attempting to reconnect...")).toBeInTheDocument();
    expect(screen.getByText("Reconnecting...")).toBeInTheDocument();
  });

  it("calls onRetry when button clicked", () => {
    render(<ConnectionLostOverlay onRetry={onRetry} />);
    fireEvent.click(screen.getByText("Try Again"));
    expect(onRetry).toHaveBeenCalled();
  });
});

describe("ModelSwitcher", () => {
  const models = [
    { id: "claude-sonnet", name: "Claude Sonnet", provider: "claude" as const, available: true },
    { id: "claude-opus", name: "Claude Opus", provider: "claude" as const, available: true, recommended: true, reason: "More capable" },
    { id: "gemini-flash", name: "Gemini Flash", provider: "gemini" as const, available: true },
    { id: "gemini-pro", name: "Gemini Pro", provider: "gemini" as const, available: false, reason: "Rate limited" },
  ];
  const onSwitch = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders available models", () => {
    render(
      <ModelSwitcher
        currentModel="claude-sonnet"
        models={models}
        onSwitch={onSwitch}
      />
    );
    expect(screen.getByText("Claude Opus")).toBeInTheDocument();
    expect(screen.getByText("Gemini Flash")).toBeInTheDocument();
  });

  it("does not show current model in list", () => {
    render(
      <ModelSwitcher
        currentModel="claude-sonnet"
        models={models}
        onSwitch={onSwitch}
      />
    );
    // Claude Sonnet should not be in the list (it's the current model)
    const sonnetButtons = screen.queryAllByRole("button").filter(
      (btn) => btn.textContent?.includes("Claude Sonnet")
    );
    expect(sonnetButtons.length).toBe(0);
  });

  it("shows recommended badge", () => {
    render(
      <ModelSwitcher
        currentModel="claude-sonnet"
        models={models}
        onSwitch={onSwitch}
      />
    );
    expect(screen.getByText("Recommended")).toBeInTheDocument();
  });

  it("shows unavailable models separately", () => {
    render(
      <ModelSwitcher
        currentModel="claude-sonnet"
        models={models}
        onSwitch={onSwitch}
      />
    );
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
    expect(screen.getByText("Rate limited")).toBeInTheDocument();
  });

  it("calls onSwitch when model selected", () => {
    render(
      <ModelSwitcher
        currentModel="claude-sonnet"
        models={models}
        onSwitch={onSwitch}
      />
    );
    fireEvent.click(screen.getByText("Claude Opus"));
    expect(onSwitch).toHaveBeenCalledWith("claude-opus");
  });
});

describe("QuickModelSwitch", () => {
  const alternativeModel = {
    id: "gemini-flash",
    name: "Gemini Flash",
    provider: "gemini" as const,
    available: true,
  };
  const onSwitch = vi.fn();

  it("renders alternative model suggestion", () => {
    render(
      <QuickModelSwitch
        currentModel="claude-sonnet"
        alternativeModel={alternativeModel}
        onSwitch={onSwitch}
      />
    );
    expect(screen.getByText(/Try/)).toBeInTheDocument();
    expect(screen.getByText("Gemini Flash")).toBeInTheDocument();
  });

  it("calls onSwitch when clicked", () => {
    render(
      <QuickModelSwitch
        currentModel="claude-sonnet"
        alternativeModel={alternativeModel}
        onSwitch={onSwitch}
      />
    );
    fireEvent.click(screen.getByRole("button"));
    expect(onSwitch).toHaveBeenCalled();
  });
});

// Toast tests require the provider wrapper
function ToastTestComponent() {
  const { addToast, removeToast, toasts } = useToast();

  return (
    <div>
      <button onClick={() => addToast({ type: "success", title: "Success!" })}>
        Add Success Toast
      </button>
      <button onClick={() => addToast({ type: "error", title: "Error!", message: "Something went wrong" })}>
        Add Error Toast
      </button>
      <div data-testid="toast-count">{toasts.length}</div>
    </div>
  );
}

describe("Toast System", () => {
  it("renders toasts from context", () => {
    render(
      <ToastProvider>
        <ToastTestComponent />
      </ToastProvider>
    );

    fireEvent.click(screen.getByText("Add Success Toast"));
    expect(screen.getByText("Success!")).toBeInTheDocument();
  });

  it("shows toast message", () => {
    render(
      <ToastProvider>
        <ToastTestComponent />
      </ToastProvider>
    );

    fireEvent.click(screen.getByText("Add Error Toast"));
    expect(screen.getByText("Error!")).toBeInTheDocument();
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
  });

  it("limits number of toasts", () => {
    render(
      <ToastProvider maxToasts={2}>
        <ToastTestComponent />
      </ToastProvider>
    );

    fireEvent.click(screen.getByText("Add Success Toast"));
    fireEvent.click(screen.getByText("Add Success Toast"));
    fireEvent.click(screen.getByText("Add Success Toast"));

    expect(screen.getByTestId("toast-count").textContent).toBe("2");
  });
});
