// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider, useToast } from "./ToastProvider";

function Trigger({ message, tone }: { message: string; tone?: "success" | "error" }) {
  const showToast = useToast();
  return (
    <button type="button" onClick={() => showToast(message, tone)}>
      Fire
    </button>
  );
}

describe("ToastProvider", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("announces toasts in a polite live region and auto-dismisses", () => {
    render(
      <ToastProvider>
        <Trigger message="Inventory quantity saved." />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Fire" }));

    const region = screen.getByRole("status");
    expect(region.getAttribute("aria-live")).toBe("polite");
    expect(screen.getByText("Inventory quantity saved.")).toBeTruthy();

    act(() => {
      vi.advanceTimersByTime(5_000);
    });
    expect(screen.queryByText("Inventory quantity saved.")).toBeNull();
  });

  it("supports manual dismissal and error tone", () => {
    render(
      <ToastProvider>
        <Trigger message="Import failed." tone="error" />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Fire" }));
    expect(screen.getByText("Import failed.").parentElement?.className).toContain("toast--error");

    fireEvent.click(screen.getByRole("button", { name: "Dismiss notification" }));
    expect(screen.queryByText("Import failed.")).toBeNull();
  });
});
