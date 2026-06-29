import { useEffect, useState } from "react";

import {
  deleteInventoryItem,
  setInventoryQuantity,
} from "../../api/inventory";
import { notifyInventoryChanged } from "../../inventory/events";
import {
  incrementQuantity,
  MAX_INVENTORY_QUANTITY,
  parseQuantityInput,
} from "../../inventory/helpers";

interface CompactInventoryEditorProps {
  partId: string;
  colorCode: number;
  ownedQuantity: number;
  catalogAvailable: boolean;
}

export function CompactInventoryEditor({
  partId,
  colorCode,
  ownedQuantity,
  catalogAvailable,
}: CompactInventoryEditorProps) {
  const [input, setInput] = useState(String(ownedQuantity));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setInput(String(ownedQuantity));
  }, [ownedQuantity]);

  async function mutate(quantity: number) {
    if (busy) return;
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      if (quantity === 0) {
        await deleteInventoryItem(partId, colorCode);
        setMessage("Inventory entry removed.");
      } else {
        await setInventoryQuantity(partId, colorCode, quantity);
        setMessage(`Total owned quantity set to ${quantity}.`);
      }
      notifyInventoryChanged();
    } catch (caught: unknown) {
      setError(
        caught instanceof Error ? caught.message : "Unable to update inventory quantity.",
      );
    } finally {
      setBusy(false);
    }
  }

  function save() {
    if (input === "0") {
      void mutate(0);
      return;
    }
    const quantity = parseQuantityInput(input);
    if (quantity === null) {
      setError("Enter a whole total quantity from 0 through 999999.");
      return;
    }
    void mutate(quantity);
  }

  const controlsDisabled = busy || !catalogAvailable;
  return (
    <div className="compact-inventory-editor">
      <span className="compact-editor-label">Owned total</span>
      <div className="quantity-controls">
        <button
          type="button"
          aria-label={`Decrease ${partId} in color ${colorCode}`}
          disabled={busy || ownedQuantity === 0 || (!catalogAvailable && ownedQuantity > 1)}
          onClick={() => void mutate(Math.max(0, ownedQuantity - 1))}
        >
          −
        </button>
        <input
          aria-label={`Total owned quantity for ${partId} in color ${colorCode}`}
          type="number"
          min="0"
          max={MAX_INVENTORY_QUANTITY}
          step="1"
          value={input}
          disabled={controlsDisabled}
          onChange={(event) => setInput(event.currentTarget.value)}
        />
        <button
          type="button"
          aria-label={`Increase ${partId} in color ${colorCode}`}
          disabled={controlsDisabled || ownedQuantity >= MAX_INVENTORY_QUANTITY}
          onClick={() => void mutate(incrementQuantity(ownedQuantity))}
        >
          +
        </button>
      </div>
      <div className="compact-editor-actions">
        <button type="button" disabled={controlsDisabled} onClick={save}>
          Set total
        </button>
        {ownedQuantity > 0 && (
          <button type="button" disabled={busy} onClick={() => void mutate(0)}>
            Remove
          </button>
        )}
      </div>
      {!catalogAvailable && (
        <small>Catalog metadata is unavailable; only removal is allowed.</small>
      )}
      {message && <small className="success-message" role="status">{message}</small>}
      {error && <small className="inline-error" role="alert">{error}</small>}
    </div>
  );
}
