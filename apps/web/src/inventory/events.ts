const INVENTORY_CHANGED_EVENT = "bricky:inventory-changed";

export function notifyInventoryChanged(): void {
  window.dispatchEvent(new Event(INVENTORY_CHANGED_EVENT));
}

export function subscribeInventoryChanged(listener: () => void): () => void {
  window.addEventListener(INVENTORY_CHANGED_EVENT, listener);
  return () => window.removeEventListener(INVENTORY_CHANGED_EVENT, listener);
}
