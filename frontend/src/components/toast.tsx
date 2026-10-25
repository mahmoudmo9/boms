import { createContext, type ReactNode, useCallback, useContext, useState } from "react";

import { Icon } from "./Icon";

type Tone = "success" | "error" | "info";
interface Toast {
  id: number;
  tone: Tone;
  text: ReactNode;
}

const ToastContext = createContext<(text: ReactNode, tone?: Tone) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: ReactNode, tone: Tone = "info") => {
    const id = Date.now() + Math.random();
    setToasts((list) => [...list, { id, tone, text }]);
    window.setTimeout(() => setToasts((list) => list.filter((x) => x.id !== id)), 5000);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-4 end-4 z-[60] flex w-80 flex-col gap-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            role="status"
            className={`pointer-events-auto flex items-start gap-2 rounded-md border border-line bg-surface px-3 py-2 text-sm shadow-lg ${
              toast.tone === "error" ? "text-danger" : toast.tone === "success" ? "text-success" : "text-fg"
            }`}
          >
            <Icon name={toast.tone === "error" ? "alert" : "check"} size={16} className="mt-0.5" />
            <div className="text-fg">{toast.text}</div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
