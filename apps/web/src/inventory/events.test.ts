import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { notifyInventoryChanged, subscribeInventoryChanged } from "./events";


let originalWindow: Window & typeof globalThis;

beforeEach(() => {
  originalWindow = globalThis.window;
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: new EventTarget(),
  });
});

afterEach(() => {
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: originalWindow,
  });
});

describe("inventory change notifications", () => {
  it("triggers and can detach a coverage refresh subscriber", () => {
    let refreshes = 0;
    const unsubscribe = subscribeInventoryChanged(() => {
      refreshes += 1;
    });

    notifyInventoryChanged();
    expect(refreshes).toBe(1);

    unsubscribe();
    notifyInventoryChanged();
    expect(refreshes).toBe(1);
  });
});
