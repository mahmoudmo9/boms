/** Phone/WhatsApp input: country (flag, name, dial code) + number. A typed "+"/"00" prefix switches the country.
 * v0.10.1 (0.4.5): the country is a Combobox with SVG flags (Windows draws emoji flags as two letters); each option
 * reads «[flag] ایران +98», the dial code isolated left-to-right; search matches the name in fa/en, ISO and dial code. */
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { api } from "../lib/api";
import { dialCode, phoneInputChange, type PhoneRegion } from "../lib/phone";
import { useFormat } from "../lib/prefs";
import { Combobox, Flag, Input, type Option } from "../design/components";

export function usePhoneRegions() {
  return useQuery({ queryKey: ["parties", "phone-regions"], queryFn: () => api<PhoneRegion[]>("/api/parties/phone-regions"), staleTime: Infinity });
}

export function regionOptions(list: PhoneRegion[], lang: string): Option[] {
  const name = (r: PhoneRegion) => (lang === "fa" ? r.name_fa : r.name_en);
  return [...list].sort((a, b) => name(a).localeCompare(name(b), lang)).map((r) => ({
    value: r.iso2, label: name(r), code: dialCode(r), leading: <Flag code={r.iso2} decorative />,
    keywords: `${r.iso2} ${r.name_fa} ${r.name_en} ${r.calling_code}`,
  }));
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
  const options = regionOptions(list, f.lang);
  return (
    <div className={`flex min-w-0 gap-1.5 ${className}`}>
      <Combobox className="w-52 shrink-0" ariaLabel={t("contacts.phoneCountry")} value={region} clearable={false} testId="phone-country"
        options={options.length ? options : [{ value: region, label: region, leading: <Flag code={region} decorative /> }]}
        onChange={(v) => v && onChange({ value, region: v })} />
      <Input id={id} className="min-w-0 flex-1" dir="ltr" type="tel" inputMode="tel" required={required}
        aria-label={t("contacts.phoneNumber")} placeholder={t("contacts.phonePlaceholder")} value={value}
        onChange={(e) => onChange(phoneInputChange({ value, region }, e.target.value, list))} />
    </div>
  );
}
