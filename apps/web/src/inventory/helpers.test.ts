import { describe, expect, it } from "vitest";

import {
  colorSwatchValue,
  decrementQuantity,
  incrementQuantity,
  inventoryEmptyMessage,
  parseQuantityInput,
} from "./helpers";

describe("inventory quantity helpers", () => {
  it("validates input boundaries", () => {
    expect(parseQuantityInput("1")).toBe(1);
    expect(parseQuantityInput("999999")).toBe(999999);
    expect(parseQuantityInput("0")).toBeNull();
    expect(parseQuantityInput("-1")).toBeNull();
    expect(parseQuantityInput("1.5")).toBeNull();
  });

  it("handles increment and decrement boundaries", () => {
    expect(incrementQuantity(999999)).toBe(999999);
    expect(decrementQuantity(2)).toBe(1);
    expect(decrementQuantity(1)).toBeNull();
  });
});

describe("inventory presentation helpers", () => {
  it("distinguishes empty inventory from an empty search", () => {
    expect(inventoryEmptyMessage(false)).toContain("inventory is empty");
    expect(inventoryEmptyMessage(true)).toContain("match these filters");
  });

  it("formats transparent colors and falls back for invalid hex", () => {
    expect(colorSwatchValue("#C91A09", 128)).toBe("rgba(201, 26, 9, 0.502)");
    expect(colorSwatchValue("invalid", 255)).toBe("rgba(128, 128, 128, 1.000)");
  });
});
