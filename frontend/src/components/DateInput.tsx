/** Text date input in the user's calendar (Jalali or Gregorian); emits a local-midnight Date or null. */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { parseDateInput } from "../lib/format";
import { useFormat } from "../lib/prefs";
import { Input } from "./ui";

export function DateInput({ value, onChange, id }: { value: Date | null; onChange: (d: Date | null) => void; id?: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const [text, setText] = useState(value ? f.date(value.toISOString()) : "");
  const [invalid, setInvalid] = useState(false);

  useEffect(() => {
    setText(value ? f.date(value.toISOString()) : "");
    // re-render when the calendar or digit style changes
  }, [value, f]);

  return (
    <Input
      id={id}
      dir="ltr"
      value={text}
      placeholder={f.calendar === "jalali" ? t("date.placeholderJalali") : t("date.placeholderGregorian")}
      aria-invalid={invalid}
      className={`w-36 text-center tabular-nums ${invalid ? "border-danger" : ""}`}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => {
        if (!text.trim()) {
          setInvalid(false);
          onChange(null);
          return;
        }
        const parsed = parseDateInput(text, f.calendar);
        setInvalid(!parsed);
        if (parsed) onChange(parsed);
      }}
    />
  );
}
