/** One event as a sentence with its object's code and a link (v0.10.1 section 1.1), used by the deal story, the
 * history cards and the events page. */
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { splitTemplate, subjectHref, subjectOf } from "../lib/eventText";
import type { EventItem } from "../lib/types";

export function useEventTemplate() {
  const { t, i18n } = useTranslation();
  return (action: string) => {
    const key = i18n.exists(`events.actions.${action}`) ? `events.actions.${action}` : "events.generic";
    return t(key, { subject: "{{subject}}" });
  };
}

export function EventSentence({ event, caseId, link = true }: { event: EventItem; caseId?: string | null; link?: boolean }) {
  const { t, i18n } = useTranslation();
  const template = useEventTemplate()(event.action);
  const subject = subjectOf(event);
  const [before, after] = splitTemplate(template);
  const noun = i18n.exists(`events.entities.${subject.type}`) ? t(`events.entities.${subject.type}`) : t("events.generic_entity");
  const label = subject.code ?? subject.name;
  const href = link && label ? subjectHref(subject, event, caseId) : null;
  const named = label ? (subject.code ? <bdi dir="ltr">{label}</bdi> : <bdi>{label}</bdi>) : null;
  return (
    <span data-testid="event-sentence">
      {before}
      {after !== null && (
        <span className="font-medium">
          {noun}
          {named && " "}
          {named && (href ? <Link to={href} className="text-accent hover:underline">{named}</Link> : named)}
        </span>
      )}
      {after}
    </span>
  );
}
