"""Listings plug into earlier modules here (loaded by ``app.core.modules.load_hooks``)."""

from app.modules.listings import convert, dashboard
from app.modules.parties.command_center import register_section
from app.modules.sourcing.inquiries import register_inquiry_cleanup

register_inquiry_cleanup(convert.reset_screening)  # deleting the inquiry puts the listing back to "reviewing"
register_section("setad", dashboard.summary)
