export const MAX_INVENTORY_QUANTITY = 999_999;

export function parseQuantityInput(value: string): number | null {
  if (!/^\d+$/.test(value)) return null;
  const quantity = Number(value);
  return Number.isSafeInteger(quantity) && quantity >= 1 && quantity <= MAX_INVENTORY_QUANTITY
    ? quantity
    : null;
}

export function incrementQuantity(quantity: number): number {
  return Math.min(MAX_INVENTORY_QUANTITY, quantity + 1);
}

export function decrementQuantity(quantity: number): number | null {
  return quantity <= 1 ? null : quantity - 1;
}

export function inventoryEmptyMessage(hasFilters: boolean): string {
  return hasFilters
    ? "No inventory items match these filters."
    : "Your personal inventory is empty.";
}

export function colorSwatchValue(colorHex: string, alpha: number): string {
  const match = /^#([0-9a-f]{6})$/i.exec(colorHex);
  const hex = match?.[1] ?? "808080";
  const red = Number.parseInt(hex.slice(0, 2), 16);
  const green = Number.parseInt(hex.slice(2, 4), 16);
  const blue = Number.parseInt(hex.slice(4, 6), 16);
  const opacity = Math.max(0, Math.min(255, alpha)) / 255;
  return `rgba(${red}, ${green}, ${blue}, ${opacity.toFixed(3)})`;
}
