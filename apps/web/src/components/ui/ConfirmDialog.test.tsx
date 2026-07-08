// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ConfirmDialog } from "./ConfirmDialog";

describe("ConfirmDialog", () => {
  afterEach(cleanup);

  const baseProps = {
    title: "Delete this model?",
    description: "This cannot be undone.",
    confirmLabel: "Delete model",
    destructive: true,
  };

  it("opens with labelled title and fires confirm and cancel", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(<ConfirmDialog open {...baseProps} onConfirm={onConfirm} onCancel={onCancel} />);

    const dialog = screen.getByRole("dialog", { hidden: true });
    expect(dialog.getAttribute("aria-labelledby")).toBe("confirm-dialog-title");
    expect(screen.getByText("Delete this model?")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Delete model", hidden: true }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Cancel", hidden: true }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("routes Escape through onCancel and keeps state ownership outside", () => {
    const onCancel = vi.fn();
    render(<ConfirmDialog open {...baseProps} onConfirm={() => undefined} onCancel={onCancel} />);
    fireEvent(screen.getByRole("dialog", { hidden: true }), new Event("cancel"));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("disables both actions while busy", () => {
    render(
      <ConfirmDialog
        open
        busy
        {...baseProps}
        onConfirm={() => undefined}
        onCancel={() => undefined}
      />,
    );
    const confirm = screen.getByRole<HTMLButtonElement>("button", {
      name: "Delete model",
      hidden: true,
    });
    const cancel = screen.getByRole<HTMLButtonElement>("button", { name: "Cancel", hidden: true });
    expect(confirm.disabled).toBe(true);
    expect(cancel.disabled).toBe(true);
  });
});
