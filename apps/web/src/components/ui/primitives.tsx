import { ReactNode } from "react";

import { nextPage, previousPage } from "../../api/catalog";
import { ModelImportStatus } from "../../api/models";
import { modelStatusLabel } from "../../models/helpers";

/** Error banner with the alert role every page previously hand-rolled. */
export function Alert({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="error" role="alert">
      <strong>{title}</strong>
      {children !== undefined && <span>{children}</span>}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="empty-state">{children}</div>;
}

interface PaginationProps {
  page: number;
  totalPages: number;
  label: string;
  onPageChange: (page: number) => void;
}

export function Pagination({ page, totalPages, label, onPageChange }: PaginationProps) {
  return (
    <div className="pagination" aria-label={label}>
      <button type="button" disabled={page <= 1} onClick={() => onPageChange(previousPage(page))}>
        Previous
      </button>
      <span>
        Page {page} of {Math.max(1, totalPages)}
      </span>
      <button
        type="button"
        disabled={page >= totalPages}
        onClick={() => onPageChange(nextPage(page, totalPages))}
      >
        Next
      </button>
    </div>
  );
}

interface SegmentedControlProps<T extends string> {
  label: string;
  value: T;
  options: readonly { value: T; label: string }[];
  onChange: (value: T) => void;
  className: string;
}

export function SegmentedControl<T extends string>({
  label,
  value,
  options,
  onChange,
  className,
}: SegmentedControlProps<T>) {
  return (
    <div className={className} role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function ModelStatusPill({ status }: { status: ModelImportStatus }) {
  return <span className={`model-status model-status--${status}`}>{modelStatusLabel(status)}</span>;
}
