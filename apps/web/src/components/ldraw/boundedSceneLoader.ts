export class ScopeLoadSupersededError extends Error {
  constructor() {
    super("A newer instruction scope replaced this load.");
    this.name = "ScopeLoadSupersededError";
  }
}

interface PendingLoad<Input, Value> {
  key: string;
  input: Input;
  controller: AbortController;
  stale: boolean;
  promise: Promise<Value>;
  resolve: (value: Value) => void;
  reject: (reason: unknown) => void;
}

/** Small ownership-aware LRU for successfully parsed bounded scenes. */
export class SceneLruCache<Value> {
  private readonly values = new Map<string, Value>();

  constructor(
    private readonly maximumSize: number,
    private readonly dispose: (value: Value) => void,
  ) {
    if (!Number.isInteger(maximumSize) || maximumSize < 1) {
      throw new Error("Scene cache size must be a positive integer.");
    }
  }

  get(key: string): Value | null {
    const value = this.values.get(key);
    if (value === undefined) return null;
    this.values.delete(key);
    this.values.set(key, value);
    return value;
  }

  set(key: string, value: Value): void {
    const replaced = this.values.get(key);
    if (replaced !== undefined && replaced !== value) this.dispose(replaced);
    this.values.delete(key);
    this.values.set(key, value);
    while (this.values.size > this.maximumSize) {
      const oldestKey = this.values.keys().next().value as string | undefined;
      if (oldestKey === undefined) break;
      const oldest = this.values.get(oldestKey);
      this.values.delete(oldestKey);
      if (oldest !== undefined) this.dispose(oldest);
    }
  }

  clear(): void {
    for (const value of this.values.values()) this.dispose(value);
    this.values.clear();
  }

  entries(): Array<[string, Value]> {
    return [...this.values.entries()];
  }
}

/** Serializes non-cancellable parsing and keeps only the newest waiting scope. */
export class LatestScopeLoader<Input, Value> {
  private readonly cache: SceneLruCache<Value>;
  private active: PendingLoad<Input, Value> | null = null;
  private pending: PendingLoad<Input, Value> | null = null;
  private namespace: string | null = null;

  constructor(
    maximumCacheSize: number,
    private readonly load: (input: Input, signal: AbortSignal) => Promise<Value>,
    private readonly dispose: (value: Value) => void,
  ) {
    this.cache = new SceneLruCache(maximumCacheSize, dispose);
  }

  setNamespace(namespace: string): void {
    if (this.namespace === namespace) return;
    this.namespace = namespace;
    this.clear();
  }

  request(key: string, input: Input): Promise<Value> {
    const cached = this.cache.get(key);
    if (cached !== null) return Promise.resolve(cached);
    if (this.active?.key === key && !this.active.stale) return this.active.promise;
    if (this.pending?.key === key && !this.pending.stale) return this.pending.promise;

    const task = this.createTask(key, input);
    if (this.active === null) {
      this.start(task);
    } else {
      this.active.stale = true;
      this.active.controller.abort();
      if (this.pending !== null) {
        this.pending.reject(new ScopeLoadSupersededError());
      }
      this.pending = task;
    }
    return task.promise;
  }

  cancel(key: string): void {
    if (this.active?.key === key) {
      this.active.stale = true;
      this.active.controller.abort();
    }
    if (this.pending?.key === key) {
      this.pending.reject(new ScopeLoadSupersededError());
      this.pending = null;
    }
  }

  clear(): void {
    this.cache.clear();
    if (this.active !== null) {
      this.active.stale = true;
      this.active.controller.abort();
    }
    if (this.pending !== null) {
      this.pending.reject(new ScopeLoadSupersededError());
      this.pending = null;
    }
  }

  cachedEntries(): Array<[string, Value]> {
    return this.cache.entries();
  }

  private createTask(key: string, input: Input): PendingLoad<Input, Value> {
    let resolve!: (value: Value) => void;
    let reject!: (reason: unknown) => void;
    const promise = new Promise<Value>((promiseResolve, promiseReject) => {
      resolve = promiseResolve;
      reject = promiseReject;
    });
    return {
      key,
      input,
      controller: new AbortController(),
      stale: false,
      promise,
      resolve,
      reject,
    };
  }

  private start(task: PendingLoad<Input, Value>): void {
    this.active = task;
    void this.load(task.input, task.controller.signal)
      .then((value) => {
        if (task.stale) {
          this.dispose(value);
          task.reject(new ScopeLoadSupersededError());
          return;
        }
        this.cache.set(task.key, value);
        task.resolve(value);
      })
      .catch((error: unknown) => {
        task.reject(task.stale ? new ScopeLoadSupersededError() : error);
      })
      .finally(() => {
        if (this.active === task) this.active = null;
        const next = this.pending;
        this.pending = null;
        if (next !== null) this.start(next);
      });
  }
}
