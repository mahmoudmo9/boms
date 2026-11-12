"""The command center's figures (v0.10.0 section 4, reference ProToday). Read only: it adds up what the finance,
execution, quotes and Setad modules already compute and calculates nothing of its own.

- ``profit_quarter``: the profit of the deals closed this quarter (frozen ``DealResult`` snapshots), per deal currency;
  the period both as a Gregorian quarter and as a Jalali season (فصل), the page shows the one of the user's calendar;
- ``win_rate``: decided quotes (accepted, partially accepted, rejected) per month over six months, and the total;
- ``tied_up``: cash tied up now in the open deals (``cash_position``: paid minus received), per currency;
- ``setad_today``: the new listings of the latest harvests that match the warning keywords, counted per keyword;
- ``cash_flow``: the open payment milestones due in the next 90 days (expected amount less what was received or paid),
  in and out per week and per currency, with the running net and the lowest point. Milestones without a due date or
  in the past are listed apart (overdue), never moved into the future."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

ZERO = Decimal(0)
HORIZON_DAYS = 90
WEEK = 7


def _quarter(today: date) -> tuple[date, date]:
    first = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
    nxt = date(first.year + (first.month + 2) // 12, (first.month + 2) % 12 + 1, 1)
    return first, nxt - timedelta(days=1)


def _season(today: date) -> tuple[date, date, tuple[int, int]]:
    """The Jalali season (quarter) of today: Farvardin, Tir, Mehr, Dey start one each."""
    from app.connectors.setad.jalali import jalali_to_gregorian
    from app.modules.sourcing.jalali import to_jalali

    jy, jm, _ = to_jalali(today)
    start_month = 3 * ((jm - 1) // 3) + 1
    start = date(*jalali_to_gregorian(jy, start_month, 1))
    ny, nm = (jy + 1, 1) if start_month == 10 else (jy, start_month + 3)
    end = date(*jalali_to_gregorian(ny, nm, 1)) - timedelta(days=1)
    return start, end, (jy, (start_month - 1) // 3 + 1)


def _bounds(first: date, last: date) -> tuple[datetime, datetime]:
    tz = datetime.now().astimezone().tzinfo or timezone.utc
    return datetime.combine(first, time.min, tz), datetime.combine(last + timedelta(days=1), time.min, tz)


def _profit(db: Session, first: date, last: date) -> dict:
    from app.modules.finance.models import DealResult

    lo, hi = _bounds(first, last)
    per: dict[str, Decimal] = defaultdict(lambda: ZERO)
    deals = 0
    for snap in db.scalars(select(DealResult).where(DealResult.computed_at >= lo, DealResult.computed_at < hi)):
        data = snap.data or {}
        actual = ((data.get("profit") or {}).get("actual") or {}).get("deal")
        if actual is None or not data.get("deal_currency"):
            continue
        per[data["deal_currency"]] += Decimal(str(actual))
        deals += 1
    return {"from": first.isoformat(), "to": last.isoformat(), "deals": deals,
            "by_currency": [{"currency": c, "profit": str(v)} for c, v in sorted(per.items(), key=lambda x: -abs(x[1]))]}


def _win_rate(db: Session, today: date) -> dict:
    from app.modules.quotes.models import Quote

    first = date(today.year, today.month, 1)
    months = []
    for back in range(5, -1, -1):
        y, m = first.year, first.month - back
        while m < 1:
            y, m = y - 1, m + 12
        months.append(date(y, m, 1))
    lo, _ = _bounds(months[0], today)
    rows = db.execute(select(Quote.status, Quote.decided_at).where(
        Quote.decided_at >= lo, Quote.status.in_(("accepted", "partially_accepted", "rejected")))).all()
    series = {m: {"won": 0, "lost": 0} for m in months}
    for status, at in rows:
        key = date(at.astimezone().year, at.astimezone().month, 1)
        if key in series:
            series[key]["won" if status != "rejected" else "lost"] += 1
    won = sum(v["won"] for v in series.values())
    decided = won + sum(v["lost"] for v in series.values())
    return {"won": won, "decided": decided, "percent": round(100 * won / decided, 1) if decided else None,
            "months": [{"month": m.isoformat(), **v} for m, v in series.items()]}


def _tied_up(db: Session) -> dict:
    from app.modules.execution.milestones import cash_position
    from app.modules.execution.models import PaymentMilestone
    from app.modules.sourcing.models import Case

    per: dict[str, Decimal] = defaultdict(lambda: ZERO)
    cases = 0
    ids = db.scalars(select(PaymentMilestone.case_id).join(Case, Case.id == PaymentMilestone.case_id)
                     .where(Case.status != "closed").distinct())
    for case_id in ids:
        actual = cash_position(db, case_id)["actual"]
        if actual:
            cases += 1
        for currency, v in actual.items():
            per[currency] += Decimal(str(v["net_tied_up"]))
    return {"cases": cases, "by_currency": [{"currency": c, "amount": str(v)} for c, v in sorted(per.items(), key=lambda x: -abs(x[1])) if v != 0]}


def _setad_today(db: Session, today: date) -> dict:
    from app.modules.listings import dashboard

    warned = dashboard.summary(db, today)["warn_new"]
    per: dict[str, int] = defaultdict(int)
    for row in warned:
        for keyword in row["keywords"]:
            per[keyword] += 1
    return {"count": len(warned), "keywords": [{"keyword": k, "count": n} for k, n in sorted(per.items(), key=lambda x: -x[1])][:6]}


def _cash_flow(db: Session, today: date) -> dict:
    from app.modules.execution.milestones import expected_amount
    from app.modules.execution.models import PaymentMilestone

    horizon = today + timedelta(days=HORIZON_DAYS)
    weeks = [today + timedelta(days=WEEK * i) for i in range((HORIZON_DAYS + WEEK - 1) // WEEK)]
    per: dict[str, list[dict]] = {}
    overdue: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"in": ZERO, "out": ZERO})
    undated = 0
    for ms in db.scalars(select(PaymentMilestone).where(PaymentMilestone.status.in_(("expected", "partly")))):
        amount, currency = expected_amount(db, ms)
        open_amount = amount - (ms.actual_amount or ZERO)
        if open_amount <= 0 or not currency:
            continue
        if ms.due_on is None:
            undated += 1
            continue
        if ms.due_on < today:
            overdue[currency][ms.direction] += open_amount
            continue
        if ms.due_on > horizon:
            continue
        rows = per.setdefault(currency, [{"week": w.isoformat(), "in": ZERO, "out": ZERO} for w in weeks])
        rows[min((ms.due_on - today).days // WEEK, len(weeks) - 1)][ms.direction] += open_amount
    out = []
    for currency, rows in per.items():
        net, lowest = ZERO, None
        for i, r in enumerate(rows):
            net += r["in"] - r["out"]
            r["net"] = net
            if lowest is None or net < rows[lowest]["net"]:
                lowest = i
        out.append({"currency": currency, "weeks": [{k: (str(v) if isinstance(v, Decimal) else v) for k, v in r.items()} for r in rows],
                    "lowest_week": lowest, "total_in": str(sum((r["in"] for r in rows), ZERO)), "total_out": str(sum((r["out"] for r in rows), ZERO))})
    out.sort(key=lambda c: -(Decimal(c["total_in"]) + Decimal(c["total_out"])))
    return {"from": today.isoformat(), "days": HORIZON_DAYS, "currencies": out,
            "overdue": [{"currency": c, "in": str(v["in"]), "out": str(v["out"])} for c, v in sorted(overdue.items())], "undated": undated}


def summary(db: Session, today: date) -> dict:
    q_first, q_last = _quarter(today)
    s_first, s_last, (jy, season) = _season(today)
    return {
        "profit_quarter": {"gregorian": _profit(db, q_first, q_last), "jalali": {**_profit(db, s_first, s_last), "year": jy, "season": season}},
        "win_rate": _win_rate(db, today),
        "tied_up": _tied_up(db),
        "setad_today": _setad_today(db, today),
        "cash_flow": _cash_flow(db, today),
    }
