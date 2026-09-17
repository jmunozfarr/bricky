// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useEffect, useState } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useDebouncedSearchParam } from "./useDebouncedSearchParam";

/*
 * Baseline coverage for `useDebouncedSearchParam`, written against the hook as
 * it stands today.  Every expectation here was observed on the current
 * implementation rather than derived from an intended one, so the file can be
 * re-run byte-identical after the render-phase ref access is removed.
 */

type HookResult = ReturnType<typeof useDebouncedSearchParam>;

/** Mirrors the hook's options interface, which the module does not export. */
interface Options {
  deleteOnChange?: string[];
}

/**
 * Every committed `location.search`, in order.  Entry 0 is the initial URL, so
 * the number of navigations is `urlLog.length - 1`.  Both hook-driven writes and
 * caller-driven navigations land here.
 */
let urlLog: string[] = [];

/**
 * Keyed on the `location` object rather than on the search string, so a
 * navigation that happens to produce an identical query string is still logged.
 * Rendered as a sibling of the harness so it survives the harness unmounting.
 */
function UrlLog() {
  const location = useLocation();
  useEffect(() => {
    urlLog.push(location.search);
  }, [location]);
  return null;
}

function Readout({ result, externalSearch }: { result: HookResult; externalSearch: string }) {
  const { query, searchInput, setSearchInput, params, setParams } = result;
  return (
    <>
      <label htmlFor="search">Search</label>
      <input
        id="search"
        value={searchInput}
        onChange={(event) => setSearchInput(event.target.value)}
      />
      <span data-testid="query">{query}</span>
      <span data-testid="params">{params.toString()}</span>
      <span data-testid="shape">
        {Object.entries(result)
          .map(([key, value]) => `${key}:${typeof value}`)
          .sort()
          .join(",")}
      </span>
      <button type="button" onClick={() => setParams(new URLSearchParams(externalSearch))}>
        External write
      </button>
    </>
  );
}

function OptionsHarness({
  options,
  externalSearch,
}: {
  options?: Options;
  externalSearch: string;
}) {
  const result = useDebouncedSearchParam(options);
  return <Readout result={result} externalSearch={externalSearch} />;
}

function NoArgHarness({ externalSearch }: { externalSearch: string }) {
  // 3.9: the hook stays callable with no argument at all.
  const result = useDebouncedSearchParam();
  return <Readout result={result} externalSearch={externalSearch} />;
}

interface HarnessState {
  options?: Options;
  /** `false` unmounts the hook while leaving the URL log mounted. */
  mounted?: boolean;
}

interface SetupArgs {
  url?: string;
  options?: Options;
  /** Target of the "External write" button, i.e. a navigation the hook did not cause. */
  externalSearch?: string;
  /** Render the variant that calls the hook with no argument at all. */
  noArg?: boolean;
}

function setup({
  url = "/catalog",
  options,
  externalSearch = "query=external",
  noArg = false,
}: SetupArgs = {}) {
  const tree = ({ options: nextOptions, mounted = true }: HarnessState) => (
    <MemoryRouter initialEntries={[url]}>
      <UrlLog />
      {mounted &&
        (noArg ? (
          <NoArgHarness externalSearch={externalSearch} />
        ) : (
          <OptionsHarness options={nextOptions} externalSearch={externalSearch} />
        ))}
    </MemoryRouter>
  );
  const view = render(tree({ options }));
  return {
    rerender: (state: HarnessState = {}) => {
      view.rerender(tree(state));
    },
  };
}

function searchBox() {
  return screen.getByLabelText<HTMLInputElement>("Search");
}

function typeSearch(value: string) {
  fireEvent.change(searchBox(), { target: { value } });
}

function advance(ms: number) {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

function clickExternalWrite() {
  fireEvent.click(screen.getByRole("button", { name: "External write" }));
}

/**
 * Returns a new array holding exactly `keys`.  `_nonce` is deliberately unused:
 * it only has to change so the copy cannot be memoised away, which is what makes
 * every render's array a genuinely fresh instance under the React Compiler as
 * well as without it.
 */
function freshKeys(keys: string[], _nonce: number): string[] {
  return [...keys];
}

/**
 * The `deleteOnChange` array committed by each render of `FreshLiteralHarness`,
 * in order.  Lets a case prove the forced re-renders really did supply new
 * instances, so an assertion about the surviving timer is never vacuous.
 */
let committedDeleteOnChange: string[][] = [];

/**
 * Mirrors `CatalogPage` / `InventoryPage`, which call the hook with an inline
 * `{ deleteOnChange: ["part"] }` literal: both the object and the array are
 * fresh on every render.  `tick` is state that neither the search input nor the
 * URL depends on, which gives the identity table an "unrelated state change"
 * re-render cause alongside the parent re-render the tree already provides.
 */
function FreshLiteralHarness({ keys }: { keys: string[] }) {
  const [tick, setTick] = useState(0);
  const deleteOnChange = freshKeys(keys, tick);
  const result = useDebouncedSearchParam({ deleteOnChange });
  useEffect(() => {
    committedDeleteOnChange.push(deleteOnChange);
  });
  return (
    <>
      {/* This harness never navigates externally, so the target is unused. */}
      <Readout result={result} externalSearch="" />
      <button type="button" onClick={() => setTick((value) => value + 1)}>
        Unrelated state change
      </button>
    </>
  );
}

function setupFreshLiteral(url: string) {
  committedDeleteOnChange = [];
  // `keys` is built outside any component, so a parent re-render also hands the
  // harness a new instance rather than the one it already holds.
  const tree = () => (
    <MemoryRouter initialEntries={[url]}>
      <UrlLog />
      <FreshLiteralHarness keys={["part"]} />
    </MemoryRouter>
  );
  const view = render(tree());
  return {
    /** Re-render the whole tree from the root. */
    parentRerender: () => {
      view.rerender(tree());
    },
    /** Bump harness-local state that touches neither the input nor the URL. */
    unrelatedStateChange: () => {
      fireEvent.click(screen.getByRole("button", { name: "Unrelated state change" }));
    },
  };
}

describe("useDebouncedSearchParam", () => {
  beforeEach(() => {
    urlLog = [];
    vi.useFakeTimers();
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("writes the trimmed query and resets page after the 300 ms window", () => {
    setup({ url: "/catalog?query=abc" });
    typeSearch("  bricks  ");

    advance(299);
    expect(urlLog).toEqual(["?query=abc"]);

    advance(1);
    expect(urlLog).toEqual(["?query=abc", "?query=bricks&page=1"]);
    expect(screen.getByTestId("params").textContent).toBe("query=bricks&page=1");
    // The resync effect then normalises the input to the trimmed value.
    expect(searchBox().value).toBe("bricks");

    advance(300);
    expect(urlLog).toHaveLength(2);
  });

  it("deletes the query param when the input is whitespace only", () => {
    setup({ url: "/catalog?query=bricks" });
    typeSearch("   ");
    advance(300);

    expect(urlLog).toEqual(["?query=bricks", "?page=1"]);
    expect(screen.getByTestId("query").textContent).toBe("");
    expect(searchBox().value).toBe("");

    advance(300);
    expect(urlLog).toHaveLength(2);
  });

  it("coalesces three changes inside one window into a single trailing write", () => {
    setup();
    typeSearch("b");
    advance(100);
    typeSearch("br");
    advance(100);
    typeSearch("bri");

    advance(299);
    expect(urlLog).toEqual([""]);

    advance(1);
    expect(urlLog).toEqual(["", "?query=bri&page=1"]);
  });

  it("schedules no timer and writes nothing while the input equals the query", () => {
    setup({ url: "/catalog?query=abc" });
    expect(vi.getTimerCount()).toBe(0);

    typeSearch("abcd");
    expect(vi.getTimerCount()).toBe(1);

    typeSearch("abc");
    expect(vi.getTimerCount()).toBe(0);

    advance(1_000);
    expect(urlLog).toEqual(["?query=abc"]);
  });

  it("clears the pending timer on unmount and writes nothing", () => {
    const { rerender } = setup();
    typeSearch("bricks");
    expect(vi.getTimerCount()).toBe(1);
    advance(100);

    rerender({ mounted: false });
    expect(vi.getTimerCount()).toBe(0);

    advance(300);
    expect(urlLog).toEqual([""]);
  });

  it("resyncs the input when the query param changes from outside the hook", () => {
    setup({ url: "/catalog?query=abc", externalSearch: "query=external" });
    clickExternalWrite();

    expect(screen.getByTestId("query").textContent).toBe("external");
    expect(searchBox().value).toBe("external");

    advance(300);
    expect(urlLog).toEqual(["?query=abc", "?query=external"]);
  });

  it("writes only query and page when called with no options", () => {
    setup({ url: "/models?query=a&part=3001", noArg: true });
    typeSearch("b");
    advance(300);

    expect(urlLog).toEqual(["?query=a&part=3001", "?query=b&part=3001&page=1"]);
  });

  it("deletes the part param when deleteOnChange lists it", () => {
    setup({ url: "/catalog?query=a&part=3001", options: { deleteOnChange: ["part"] } });
    typeSearch("b");
    advance(300);

    expect(urlLog).toEqual(["?query=a&part=3001", "?query=b&page=1"]);
  });

  it("returns query, searchInput, setSearchInput, params and setParams", () => {
    setup({ url: "/catalog?query=abc" });

    expect(screen.getByTestId("shape").textContent).toBe(
      "params:object,query:string,searchInput:string,setParams:function,setSearchInput:function",
    );
    expect(screen.getByTestId("query").textContent).toBe("abc");
    expect(screen.getByTestId("params").textContent).toBe("query=abc");
    expect(searchBox().value).toBe("abc");
  });

  it("behaves identically with no argument and with an empty options object", () => {
    const runOnce = (args: SetupArgs) => {
      urlLog = [];
      setup(args);
      typeSearch("b");
      advance(300);
      const log = [...urlLog];
      cleanup();
      return log;
    };

    const noArgLog = runOnce({ url: "/catalog?query=a", noArg: true });
    const emptyOptionsLog = runOnce({ url: "/catalog?query=a", options: {} });

    expect(noArgLog).toEqual(["?query=a", "?query=b&page=1"]);
    expect(emptyOptionsLog).toEqual(noArgLog);
  });

  it("deletes every key listed in a multi-key deleteOnChange", () => {
    setup({
      url: "/catalog?query=a&part=3001&color=4",
      options: { deleteOnChange: ["part", "color"] },
    });
    typeSearch("b");
    advance(300);

    expect(urlLog).toEqual(["?query=a&part=3001&color=4", "?query=b&page=1"]);
  });

  it("treats a deleteOnChange key that is absent from the URL as a no-op", () => {
    setup({ url: "/catalog?query=a", options: { deleteOnChange: ["part"] } });
    typeSearch("b");
    advance(300);

    expect(urlLog).toEqual(["?query=a", "?query=b&page=1"]);
  });

  it("resets page to 1 even when it was already 1", () => {
    setup({ url: "/catalog?query=a&page=1" });
    typeSearch("b");
    advance(300);

    expect(urlLog).toEqual(["?query=a&page=1", "?query=b&page=1"]);
    expect(screen.getByTestId("params").textContent).toBe("query=b&page=1");
  });

  it("leaves unrelated params untouched", () => {
    setup({ url: "/catalog?category=Brick&status=owned&query=a" });
    typeSearch("b");
    advance(300);

    expect(urlLog).toEqual([
      "?category=Brick&status=owned&query=a",
      "?category=Brick&status=owned&query=b&page=1",
    ]);
  });

  /*
   * Property 2 — sequence equivalence.  An enumerated `it.each` table stands in
   * for generators (no property-based library is installed in `apps/web`), each
   * script asserted against the write log captured from the unfixed hook.
   */
  type Step =
    | { kind: "input"; value: string }
    | { kind: "advance"; ms: number }
    | { kind: "external" }
    | { kind: "unmount" };

  interface Sequence {
    name: string;
    url: string;
    options?: Options;
    externalSearch?: string;
    steps: Step[];
    expected: string[];
  }

  const sequences: Sequence[] = [
    {
      name: "single change",
      url: "/catalog?query=a",
      steps: [
        { kind: "input", value: "ab" },
        { kind: "advance", ms: 300 },
      ],
      expected: ["?query=a", "?query=ab&page=1"],
    },
    {
      name: "rapid burst",
      url: "/catalog?query=a",
      options: { deleteOnChange: ["part"] },
      steps: [
        { kind: "input", value: "ab" },
        { kind: "advance", ms: 100 },
        { kind: "input", value: "abc" },
        { kind: "advance", ms: 100 },
        { kind: "input", value: "abcd" },
        { kind: "advance", ms: 300 },
      ],
      expected: ["?query=a", "?query=abcd&page=1"],
    },
    {
      name: "change then revert",
      url: "/catalog?query=a",
      steps: [
        { kind: "input", value: "ab" },
        { kind: "advance", ms: 100 },
        { kind: "input", value: "a" },
        { kind: "advance", ms: 300 },
      ],
      expected: ["?query=a"],
    },
    {
      name: "change then unmount",
      url: "/catalog?query=a",
      steps: [
        { kind: "input", value: "ab" },
        { kind: "advance", ms: 100 },
        { kind: "unmount" },
        { kind: "advance", ms: 300 },
      ],
      expected: ["?query=a"],
    },
    {
      name: "external change then local change",
      url: "/catalog?query=a",
      externalSearch: "query=ext",
      steps: [
        { kind: "external" },
        { kind: "advance", ms: 300 },
        { kind: "input", value: "ext2" },
        { kind: "advance", ms: 300 },
      ],
      expected: ["?query=a", "?query=ext", "?query=ext2&page=1"],
    },
  ];

  it.each(sequences)("keeps the write log stable for: $name", (sequence) => {
    const { rerender } = setup({
      url: sequence.url,
      options: sequence.options,
      externalSearch: sequence.externalSearch,
    });

    for (const step of sequence.steps) {
      switch (step.kind) {
        case "input":
          typeSearch(step.value);
          break;
        case "advance":
          advance(step.ms);
          break;
        case "external":
          clickExternalWrite();
          break;
        case "unmount":
          rerender({ options: sequence.options, mounted: false });
          break;
      }
    }

    expect(urlLog).toEqual(sequence.expected);
  });

  /*
   * Property 3 — latest option value at write time.  An enumerated `it.each`
   * table over key-list transitions stands in for generators.  Task 1.1's probe
   * passed, so the selected implementation reads the keys when the timer fires
   * and never makes the option reactive: the write lands 300 ms after the
   * *input* change, and a key list swapped mid-debounce does not restart the
   * timer.  (The rejected derived-key fallback would have restarted it on the
   * option change; that branch was not taken.)
   *
   * **Validates: Requirements 2.5**
   */
  const latestValueUrl = "/catalog?query=a&part=3001&color=4";
  const latestValueSearch = "?query=a&part=3001&color=4";
  const asOptions = (keys?: string[]): Options | undefined =>
    keys ? { deleteOnChange: keys } : undefined;

  interface LatestValueCase {
    name: string;
    /** Keys committed by the render that scheduled the timer. */
    initial?: string[];
    /** Keys committed mid-debounce; these are the ones the write must honour. */
    next?: string[];
    /** Search string written 300 ms after the input change. */
    expected: string;
  }

  const latestValueCases: LatestValueCase[] = [
    {
      name: '["part"] -> ["part", "color"] deletes both keys',
      initial: ["part"],
      next: ["part", "color"],
      expected: "?query=b&page=1",
    },
    {
      name: 'undefined -> ["part"] deletes part',
      next: ["part"],
      expected: "?query=b&color=4&page=1",
    },
    {
      name: '["part"] -> undefined deletes nothing',
      initial: ["part"],
      expected: "?query=b&part=3001&color=4&page=1",
    },
  ];

  it.each(latestValueCases)(
    "deletes the keys from the most recently committed render: $name",
    ({ initial, next, expected }) => {
      const { rerender } = setup({ url: latestValueUrl, options: asOptions(initial) });
      typeSearch("b");
      expect(vi.getTimerCount()).toBe(1);

      // Half-way through the window, commit a different key list.
      advance(150);
      rerender({ options: asOptions(next) });
      expect(vi.getTimerCount()).toBe(1);

      // 299 ms after the input change nothing has been written, so the option
      // change did not restart the timer (a restart would defer this to 450 ms).
      advance(149);
      expect(urlLog).toEqual([latestValueSearch]);

      // At 300 ms the write lands, carrying the most recently committed keys.
      advance(1);
      expect(urlLog).toEqual([latestValueSearch, expected]);

      // Exactly one write, and nothing left pending behind it.
      advance(300);
      expect(urlLog).toEqual([latestValueSearch, expected]);
      expect(vi.getTimerCount()).toBe(0);
    },
  );

  /*
   * Property 4 — equal-but-fresh option identity is not reactive.  An enumerated
   * `it.each` table over the number of extra re-renders and over what caused them
   * stands in for generators.  The debounce effect depends on
   * `[query, searchInput, setParams]`, none of which a bare re-render changes, so
   * a new `["part"]` instance must neither re-run the effect nor restart the
   * pending timer: the single trailing write still lands 300 ms after the *input*
   * change, however many renders happened in between.  Were `deleteOnChange` ever
   * to become a real dependency, each re-render would push the write out by a
   * further 300 ms and the 299 ms / 300 ms assertions below would fail.
   *
   * **Validates: Requirements 2.6**
   */
  const freshLiteralUrl = "/catalog?query=a&part=3001";
  const freshLiteralSearch = "?query=a&part=3001";
  const freshLiteralWrite = "?query=b&page=1";

  const causes = ["a parent re-render", "an unrelated state change"] as const;

  interface IdentityCase {
    cause: (typeof causes)[number];
    /** Renders forced after the timer was already pending. */
    extraRenders: number;
  }

  const identityCases: IdentityCase[] = causes.flatMap((cause) =>
    [1, 2, 5].map((extraRenders) => ({ cause, extraRenders })),
  );

  it.each(identityCases)(
    "keeps one write at the 300 ms mark across $extraRenders fresh literals from $cause",
    ({ cause, extraRenders }) => {
      const harness = setupFreshLiteral(freshLiteralUrl);
      const forceRerender =
        cause === "a parent re-render" ? harness.parentRerender : harness.unrelatedStateChange;

      typeSearch("b");
      expect(vi.getTimerCount()).toBe(1);

      // Two thirds of the way through the window, re-render N more times.
      advance(200);
      const committedBefore = committedDeleteOnChange.length;
      for (let index = 0; index < extraRenders; index += 1) forceRerender();

      // Each forced render really happened and really did commit a new array
      // instance holding the same keys — otherwise the timing below proves
      // nothing.  The slice starts one entry early to include the literal the
      // pending timer was scheduled with.
      const forcedLiterals = committedDeleteOnChange.slice(committedBefore - 1);
      expect(forcedLiterals).toEqual(Array.from({ length: extraRenders + 1 }, () => ["part"]));
      expect(new Set(forcedLiterals).size).toBe(extraRenders + 1);
      expect(vi.getTimerCount()).toBe(1);

      // 299 ms after the input change, still nothing written.
      advance(99);
      expect(urlLog).toEqual([freshLiteralSearch]);

      // The write lands at exactly 300 ms after the input change, not 300 ms
      // after the last re-render, and deletes the key from the fresh literal.
      advance(1);
      expect(urlLog).toEqual([freshLiteralSearch, freshLiteralWrite]);

      // Exactly one write, with nothing left pending behind it.
      advance(300);
      expect(urlLog).toEqual([freshLiteralSearch, freshLiteralWrite]);
      expect(vi.getTimerCount()).toBe(0);
    },
  );
});
