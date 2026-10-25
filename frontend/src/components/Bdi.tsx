import type { ReactNode } from "react";

/** Isolates mixed-direction values (codes, file names, emails, numbers) from the surrounding text. */
export function Bdi({ children, ltr = false, className }: { children: ReactNode; ltr?: boolean; className?: string }) {
  return (
    <bdi dir={ltr ? "ltr" : undefined} className={className}>
      {children}
    </bdi>
  );
}
