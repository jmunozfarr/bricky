import { useEffect, useState } from "react";

import { useToast } from "../ui/ToastProvider";
import { useDeleteInventoryItem, useSetInventoryQuantity } from "../../queries/hooks";
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
  const [inputError, setInputError] = useState<string | null>(null);
  const showToast = useToast();
  const setQuantity = useSetInventoryQuantity();
  const deleteItem = useDeleteInventoryItem();
  const busy = setQuantity.isPending || deleteItem.isPending;
  const mutationError = setQuantity.error ?? deleteItem.error;
  const error =
    inputError ??
    (mutationError === null
      ? null
      : mutationError instanceof Error
        ? mutationError.message
        : "Unable to update inventory quantity.");

  useEffect(() => {
    setInput(String(ownedQuantity));
  }, [ownedQuantity]);

  function mutate(quantity: number) {
    if (busy) return;
    setInputError(null);
    if (quantity === 0) {
      deleteItem.mutate(
        { partId, colorCode },
        { onSuccess: () => showToast(`Removed ${partId} from the inventory.`) },
      );
    } else {
      setQuantity.mutate(
        { partId, colorCode, quantity },
        { onSuccess: () => showToast(`Owned quantity for ${partId} set to ${quantity}.`) },
      );
    }
  }

  function save() {
    if (input === "0") {
      mutate(0);
      return;
    }
    const quantity = parseQuantityInput(input);
    if (quantity === null) {
      setInputError("Enter a whole total quantity from 0 through 999999.");
      return;
    }
    mutate(quantity);
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
          onClick={() => mutate(Math.max(0, ownedQuantity - 1))}
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
          onClick={() => mutate(incrementQuantity(ownedQuantity))}
        >
          +
        </button>
      </div>
      <div className="compact-editor-actions">
        <button type="button" disabled={controlsDisabled} onClick={save}>
          Set total
        </button>
        {ownedQuantity > 0 && (
          <button type="button" disabled={busy} onClick={() => mutate(0)}>
            Remove
          </button>
        )}
      </div>
      {!catalogAvailable && (
        <small>Catalog metadata is unavailable; only removal is allowed.</small>
      )}
      {error && (
        <small className="inline-error" role="alert">
          {error}
        </small>
      )}
    </div>
  );
}
