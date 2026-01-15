/**
 * Tests for degraded mode UI components.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { DegradedModeBanner } from "@/components/degraded-mode-banner";

// Mock the hook
const mockUseProviderStatus = vi.fn();

vi.mock("@/hooks/use-provider-status", () => ({
  useProviderStatus: () => mockUseProviderStatus(),
}));

describe("DegradedModeBanner", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not render when not degraded", () => {
    mockUseProviderStatus.mockReturnValue({
      isDegraded: false,
      unavailableProviders: [],
      recoveryEta: null,
      status: null,
    });

    const { container } = render(<DegradedModeBanner />);
    expect(container.firstChild).toBeNull();
  });

  it("shows limited functionality when degraded", () => {
    mockUseProviderStatus.mockReturnValue({
      isDegraded: true,
      unavailableProviders: ["claude"],
      recoveryEta: null,
      status: { status: "degraded" },
    });

    render(<DegradedModeBanner />);

    expect(screen.getByText("Limited functionality")).toBeInTheDocument();
    expect(screen.getByText("(claude unavailable)")).toBeInTheDocument();
  });

  it("shows multiple unavailable providers", () => {
    mockUseProviderStatus.mockReturnValue({
      isDegraded: true,
      unavailableProviders: ["claude", "gemini"],
      recoveryEta: null,
      status: { status: "degraded" },
    });

    render(<DegradedModeBanner />);

    expect(
      screen.getByText("(claude, gemini unavailable)"),
    ).toBeInTheDocument();
  });

  it("shows queue position when provided", () => {
    mockUseProviderStatus.mockReturnValue({
      isDegraded: true,
      unavailableProviders: ["claude"],
      recoveryEta: null,
      status: { status: "degraded" },
    });

    render(<DegradedModeBanner queuePosition={3} />);

    expect(screen.getByText(/position: 3/)).toBeInTheDocument();
  });

  it("shows estimated wait time when queued", () => {
    mockUseProviderStatus.mockReturnValue({
      isDegraded: true,
      unavailableProviders: ["claude"],
      recoveryEta: null,
      status: { status: "degraded" },
    });

    render(<DegradedModeBanner queuePosition={2} estimatedWaitMs={30000} />);

    expect(screen.getByText(/estimated wait: 30s/)).toBeInTheDocument();
  });

  it("shows recovery ETA when available", () => {
    mockUseProviderStatus.mockReturnValue({
      isDegraded: true,
      unavailableProviders: ["claude"],
      recoveryEta: 60000, // 60 seconds
      status: { status: "degraded" },
    });

    render(<DegradedModeBanner />);

    expect(screen.getByText("Estimated recovery: 1m")).toBeInTheDocument();
  });

  it("can be dismissed", () => {
    const onDismiss = vi.fn();
    mockUseProviderStatus.mockReturnValue({
      isDegraded: true,
      unavailableProviders: ["claude"],
      recoveryEta: null,
      status: { status: "degraded" },
    });

    render(<DegradedModeBanner onDismiss={onDismiss} />);

    const dismissButton = screen.getByLabelText("Dismiss banner");
    fireEvent.click(dismissButton);

    expect(onDismiss).toHaveBeenCalled();
  });

  it("shows recovery message when providers recover", async () => {
    // Start degraded
    mockUseProviderStatus.mockReturnValue({
      isDegraded: true,
      unavailableProviders: ["claude"],
      recoveryEta: null,
      status: { status: "degraded" },
    });

    const { rerender } = render(<DegradedModeBanner />);
    expect(screen.getByText("Limited functionality")).toBeInTheDocument();

    // Simulate recovery
    mockUseProviderStatus.mockReturnValue({
      isDegraded: false,
      unavailableProviders: [],
      recoveryEta: null,
      status: { status: "healthy" },
    });

    rerender(<DegradedModeBanner />);

    expect(screen.getByText(/All providers recovered/)).toBeInTheDocument();
  });

  it("auto-dismisses recovery message after delay", async () => {
    // Start degraded
    mockUseProviderStatus.mockReturnValue({
      isDegraded: true,
      unavailableProviders: ["claude"],
      recoveryEta: null,
      status: { status: "degraded" },
    });

    const { rerender } = render(<DegradedModeBanner />);

    // Simulate recovery
    mockUseProviderStatus.mockReturnValue({
      isDegraded: false,
      unavailableProviders: [],
      recoveryEta: null,
      status: { status: "healthy" },
    });

    rerender(<DegradedModeBanner />);
    expect(screen.getByText(/All providers recovered/)).toBeInTheDocument();

    // Fast-forward past auto-dismiss timeout
    act(() => {
      vi.advanceTimersByTime(4000);
    });

    rerender(<DegradedModeBanner />);

    // Banner should be gone
    expect(
      screen.queryByText(/All providers recovered/),
    ).not.toBeInTheDocument();
  });

  it("formats wait time in minutes when > 60s", () => {
    mockUseProviderStatus.mockReturnValue({
      isDegraded: true,
      unavailableProviders: ["claude"],
      recoveryEta: null,
      status: { status: "degraded" },
    });

    render(<DegradedModeBanner queuePosition={5} estimatedWaitMs={120000} />);

    expect(screen.getByText(/estimated wait: 2m/)).toBeInTheDocument();
  });

  it("stays hidden after manual dismiss until next degradation", () => {
    mockUseProviderStatus.mockReturnValue({
      isDegraded: true,
      unavailableProviders: ["claude"],
      recoveryEta: null,
      status: { status: "degraded" },
    });

    const { rerender } = render(<DegradedModeBanner />);

    // Dismiss
    fireEvent.click(screen.getByLabelText("Dismiss banner"));

    // Should be hidden
    expect(screen.queryByText("Limited functionality")).not.toBeInTheDocument();

    // Re-render - still hidden because still degraded (same degradation)
    rerender(<DegradedModeBanner />);
    expect(screen.queryByText("Limited functionality")).not.toBeInTheDocument();
  });
});
