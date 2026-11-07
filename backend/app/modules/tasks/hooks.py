"""Tasks plug into earlier modules here (loaded by ``app.core.modules.load_hooks``)."""

from app.modules.parties.command_center import register_section
from app.modules.sourcing.inquiries import register_case_cleanup
from app.modules.tasks import cleanup, dashboard

register_section("tasks", dashboard.summary)     # command center «کارها»
register_case_cleanup(0, cleanup.cleanup_case)   # the case's tasks, before every other module's rows
