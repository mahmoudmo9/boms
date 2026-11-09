"""Sourcing plugs into later core services here (loaded by ``app.core.modules.load_hooks``)."""

from app.modules.codes.service import register
from app.modules.sourcing.models import Case, Inquiry, Rfq

# v0.9.0: record codes INQ-, CS-, RFQ-
register("inquiry", Inquiry, link=lambda _db, r: f"/sourcing/inquiries/{r.id}")
register("case", Case, link=lambda _db, r: f"/cases/{r.id}")
register("rfq", Rfq, link=lambda _db, r: f"/cases/{r.case_id}?tab=rfqs&rfq={r.id}")
