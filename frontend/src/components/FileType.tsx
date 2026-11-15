/** A file's type with an icon (v0.10.1 section 3.5); the MIME string is only the tooltip. */
import { useTranslation } from "react-i18next";

import { Icon } from "../design/components";
import { FILE_ICON, fileKind } from "../lib/fileKind";

export function FileType({ mime, name }: { mime: string | null | undefined; name?: string | null }) {
  const { t } = useTranslation();
  const kind = fileKind(mime, name);
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-fg-2" title={mime ?? undefined} data-testid="file-type" data-kind={kind}>
      <Icon name={FILE_ICON[kind]} size={14} className="text-muted" />{t(`files.kinds.${kind}`)}
    </span>
  );
}
