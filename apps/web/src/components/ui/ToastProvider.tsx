import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from "react";

export type ToastTone = "success" | "error";

interface ToastEntry {
  id: number;
  tone: ToastTone;
  message: string;
}

type ShowToast = (message: string, tone?: ToastTone) => void;

const ToastContext = createContext<ShowToast | null>(null);

const TOAST_DISMISS_MS = 4_500;

export function useToast(): ShowToast {
  const show = useContext(ToastContext);
  if (show === null) {
    throw new Error("useToast requires a ToastProvider ancestor");
  }
  return show;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastEntry[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const show = useCallback<ShowToast>(
    (message, tone = "success") => {
      const id = nextId.current;
      nextId.current += 1;
      setToasts((current) => [...current, { id, tone, message }]);
      window.setTimeout(() => dismiss(id), TOAST_DISMISS_MS);
    },
    [dismiss],
  );

  const value = useMemo(() => show, [show]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-region" role="status" aria-live="polite">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast toast--${toast.tone}`}>
            <span>{toast.message}</span>
            <button
              type="button"
              aria-label="Dismiss notification"
              onClick={() => dismiss(toast.id)}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
