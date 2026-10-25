/** Phone/WhatsApp input: country (flag, name, dial code) + number. A typed "+"/"00" prefix switches the country. */
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { api } from "../lib/api";
import { flagEmoji, phoneInputChange, type PhoneRegion } from "../lib/phone";
import { useFormat } from "../lib/prefs";
import { Input, Select } from "./ui";

export function usePhoneRegions() {
  return useQuery({ queryKey: ["parties", "phone-regions"], queryFn: () => api<PhoneRegion[]>("/api/parties/phone-regions"), staleTime: Infinity });
}

export function PhoneInput({ value, region, onChange, id, required, className = "" }: {
  value: string;
  region: string;
  onChange: (next: { value: string; region: string }) => void;
  id?: string;
  required?: boolean;
  className?: string;
}) {
  const { t } = useTranslation();
  const f = useFormat();
  const regions = usePhoneRegions();
  const list = regions.data ?? [];
  const sorted = [...list].sort((a, b) => (f.lang === "fa" ? a.name_fa.localeCompare(b.name_fa, "fa") : a.name_en.localeCompare(b.name_en, "en")));
  return (
    <div className={`flex min-w-0 gap-1.5 ${className}`}>
      <Select className="w-40 shrink-0" dir="ltr" aria-label={t("contacts.phoneCountry")} value={region}
        onChange={(e) => onChange({ value, region: e.target.value })}>
        {sorted.length === 0 && <option value={region}>{flagEmoji(region)} {region}</option>}
        {sorted.map((r) => (
          // the select is dir="ltr" so "+971" keeps its order next to a Persian name (Chrome ignores bidi marks here)
          <option key={r.iso2} value={r.iso2}>{`${flagEmoji(r.iso2)} ${f.lang === "fa" ? r.name_fa : r.name_en} +${r.calling_code}`}</option>
        ))}
      </Select>
      <Input id={id} className="min-w-0 flex-1" dir="ltr" type="tel" inputMode="tel" required={required}
        aria-label={t("contacts.phoneNumber")} placeholder={t("contacts.phonePlaceholder")} value={value}
        onChange={(e) => onChange(phoneInputChange({ value, region }, e.target.value, list))} />
    </div>
  );
}
