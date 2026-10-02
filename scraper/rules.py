#!/usr/bin/env python3
"""The decision described in rules.md: bid, manual check or skip.

Only client figures are used: total spend and the average hourly rate the client has paid.
"""
import re

BID = 'bid'
MANUAL = 'manual check'
SKIP = 'skip'
SPEND_LIMIT = 100_000
HIGH_RATE = 20.0
LOW_RATE = 10.0


def amount(text):
    """'$301701' or '$2 037 596' -> 301701.0; None when there is no figure."""
    if not text:
        return None
    digits = re.sub(r'[^\d.]', '', str(text))
    try:
        return float(digits) if digits else None
    except ValueError:
        return None


def decide(client):
    """(result, why) for one client block."""
    client = client or {}
    spent = amount(client.get('total spent'))
    rate = amount(client.get('avg hourly rate'))

    if spent is None and rate is None:
        return BID, 'new client: Vollna shows no spend and no hourly rate'
    if spent is None or rate is None:
        return MANUAL, 'half-missing figures: spend=%s, rate=%s' % (client.get('total spent'),
                                                                   client.get('avg hourly rate'))
    if spent >= SPEND_LIMIT:
        if rate >= HIGH_RATE:
            return BID, 'spent $%.0f (>= $100K) and pays $%.2f/hr (>= $20)' % (spent, rate)
        return MANUAL, 'spent $%.0f (>= $100K) but pays $%.2f/hr (< $20)' % (spent, rate)
    if rate <= LOW_RATE:
        return SKIP, 'spent $%.0f (< $100K) and pays $%.2f/hr (<= $10)' % (spent, rate)
    return MANUAL, 'spent $%.0f (< $100K) and pays $%.2f/hr (> $10)' % (spent, rate)
