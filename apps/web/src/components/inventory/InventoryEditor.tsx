import { useEffect, useMemo, useState } from "react";

import { getColors, LDrawColor } from "../../api/catalog";
import {
  deleteInventoryItem,
  getInventoryVariants,
  InventoryItem,
  setInventoryQuantity,
} from "../../api/inventory";
import { notifyInventoryChanged } from "../../inventory/events";
import { colorSwatchValue, parseQuantityInput } from "../../inventory/helpers";

interface InventoryEditorProps {
  partId: string;
}

export function InventoryEditor({ partId }: InventoryEditorProps) {
  const [colors, setColors] = useState<LDrawColor[]>([]);
  const [variants, setVariants] = useState<InventoryItem[]>([]);
  const [selectedCode, setSelectedCode] = useState<number | null>(null);
  const [quantityInput, setQuantityInput] = useState("1");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    void Promise.all([
      getColors(controller.signal),
      getInventoryVariants(partId, controller.signal),
    ])
      .then(([loadedColors, loadedVariants]) => {
        setColors(loadedColors);
        setVariants(loadedVariants);
        const defaultColor = loadedColors.find((color) => color.code === 4) ?? loadedColors[0];
        setSelectedCode(defaultColor?.code ?? null);
        setQuantityInput(
          String(
            loadedVariants.find((variant) => variant.colorCode === defaultColor?.code)?.quantity ??
              1,
          ),
        );
        setLoading(false);
      })
      .catch((caught: unknown) => {
        if (!(caught instanceof DOMException && caught.name === "AbortError")) {
          setError(caught instanceof Error ? caught.message : "Unable to load inventory data");
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [partId]);

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
    setError(null);
    // The input must reset only when the selected color changes; reacting to
    // quantity refreshes would clobber in-progress edits and saved messages.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCode]);

  async function save() {
    const quantity = parseQuantityInput(quantityInput);
    if (selectedCode === null || quantity === null) {
      setError("Quantity must be a whole number from 1 through 999999.");
      return;
    }
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const saved = await setInventoryQuantity(partId, selectedCode, quantity);
      setVariants((current) => [
        ...current.filter((item) => item.colorCode !== selectedCode),
        saved,
      ]);
      setMessage("Inventory quantity saved.");
      notifyInventoryChanged();
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : "Unable to save quantity");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (selectedCode === null) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await deleteInventoryItem(partId, selectedCode);
      setVariants((current) => current.filter((item) => item.colorCode !== selectedCode));
      setQuantityInput("1");
      setMessage("Inventory item removed.");
      notifyInventoryChanged();
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : "Unable to remove item");
    } finally {
      setBusy(false);
    }
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
            <button type="button" onClick={() => void save()} disabled={busy}>
              Save quantity
            </button>
            {currentVariant && (
              <button type="button" onClick={() => void remove()} disabled={busy}>
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
