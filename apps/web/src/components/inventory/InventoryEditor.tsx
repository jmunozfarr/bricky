import { useEffect, useMemo, useState } from "react";

import {
  useColors,
  useDeleteInventoryItem,
  useInventoryVariants,
  useSetInventoryQuantity,
} from "../../queries/hooks";
import { colorSwatchValue, parseQuantityInput } from "../../inventory/helpers";

interface InventoryEditorProps {
  partId: string;
}

export function InventoryEditor({ partId }: InventoryEditorProps) {
  const colorsQuery = useColors();
  const variantsQuery = useInventoryVariants(partId);
  const setQuantity = useSetInventoryQuantity();
  const deleteItem = useDeleteInventoryItem();
  const colors = useMemo(() => colorsQuery.data ?? [], [colorsQuery.data]);
  const variants = useMemo(() => variantsQuery.data ?? [], [variantsQuery.data]);
  const [selectedCode, setSelectedCode] = useState<number | null>(null);
  const [quantityInput, setQuantityInput] = useState("1");
  const [message, setMessage] = useState<string | null>(null);
  const [inputError, setInputError] = useState<string | null>(null);
  const loading = colorsQuery.isPending || variantsQuery.isPending;
  const busy = setQuantity.isPending || deleteItem.isPending;
  const loadError = colorsQuery.error ?? variantsQuery.error;
  const mutationError = setQuantity.error ?? deleteItem.error;
  const surfacedError = inputError ?? loadError ?? mutationError;
  const error =
    surfacedError === null
      ? null
      : typeof surfacedError === "string"
        ? surfacedError
        : surfacedError instanceof Error
          ? surfacedError.message
          : "Unable to load inventory data";

  // Pick the default color once both lists are available.
  useEffect(() => {
    if (selectedCode !== null || colors.length === 0 || variantsQuery.data === undefined) return;
    const defaultColor = colors.find((color) => color.code === 4) ?? colors[0];
    setSelectedCode(defaultColor?.code ?? null);
    setQuantityInput(
      String(variants.find((variant) => variant.colorCode === defaultColor?.code)?.quantity ?? 1),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [colors, variantsQuery.data]);

  const selectedColor = useMemo(
    () => colors.find((color) => color.code === selectedCode) ?? null,
    [colors, selectedCode],
  );
  const currentVariant = useMemo(
    () => variants.find((variant) => variant.colorCode === selectedCode) ?? null,
    [selectedCode, variants],
  );

  useEffect(() => {
    setQuantityInput(String(currentVariant?.quantity ?? 1));
    setMessage(null);
    setInputError(null);
    // The input must reset only when the selected color changes; reacting to
    // quantity refreshes would clobber in-progress edits and saved messages.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCode]);

  function save() {
    const quantity = parseQuantityInput(quantityInput);
    if (selectedCode === null || quantity === null) {
      setInputError("Quantity must be a whole number from 1 through 999999.");
      return;
    }
    setInputError(null);
    setMessage(null);
    setQuantity.mutate(
      { partId, colorCode: selectedCode, quantity },
      { onSuccess: () => setMessage("Inventory quantity saved.") },
    );
  }

  function remove() {
    if (selectedCode === null) return;
    setInputError(null);
    setMessage(null);
    deleteItem.mutate(
      { partId, colorCode: selectedCode },
      {
        onSuccess: () => {
          setQuantityInput("1");
          setMessage("Inventory item removed.");
        },
      },
    );
  }

  return (
    <section className="inventory-editor" aria-labelledby="inventory-editor-title">
      <div>
        <p className="eyebrow">Local workspace</p>
        <h3 id="inventory-editor-title">Personal inventory</h3>
      </div>
      {loading ? (
        <p>Loading inventory colors…</p>
      ) : colors.length === 0 ? (
        <p>Official colors are not indexed.</p>
      ) : (
        <div className="inventory-editor-fields">
          <label>
            <span>Official color</span>
            <select
              value={selectedCode ?? ""}
              onChange={(event) => setSelectedCode(Number(event.currentTarget.value))}
              disabled={busy}
            >
              {colors.map((color) => (
                <option key={color.code} value={color.code}>
                  {color.name} ({color.code})
                </option>
              ))}
            </select>
          </label>
          <div className="selected-color">
            <span
              className="color-swatch"
              style={{
                backgroundColor: colorSwatchValue(
                  selectedColor?.valueHex ?? "#808080",
                  selectedColor?.alpha ?? 255,
                ),
              }}
            />
            <span>Owned now: {currentVariant?.quantity ?? 0}</span>
          </div>
          <label>
            <span>Quantity</span>
            <input
              type="number"
              min="1"
              max="999999"
              step="1"
              value={quantityInput}
              onChange={(event) => setQuantityInput(event.currentTarget.value)}
              disabled={busy}
            />
          </label>
          <div className="inventory-editor-actions">
            <button type="button" onClick={save} disabled={busy}>
              Save quantity
            </button>
            {currentVariant && (
              <button type="button" onClick={remove} disabled={busy}>
                Remove
              </button>
            )}
          </div>
        </div>
      )}
      {message && (
        <p className="success-message" role="status">
          {message}
        </p>
      )}
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
