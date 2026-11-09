"""The AI module registers itself with earlier modules: the case cascade (drafts, the case's «فقط محلی») and the
command center (the month's AI spending against the cap)."""
from app.modules.ai import drafts
from app.modules.parties.command_center import register_section
from app.modules.sourcing.inquiries import register_case_cleanup

register_case_cleanup(30, drafts.case_cleanup)


def _spending(db, _today) -> dict:
    from app.modules.ai import service

    return {**service.usage(db), "configured": service.configured(db)}


register_section("ai", _spending)     # command center: the month's AI spending and the cap
