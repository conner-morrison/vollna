#!/usr/bin/env python3
"""Tells open control-panel pages that something changed, so they redraw without polling.

Anything that changes what the panel shows calls changed(); the /api/events stream waits on it and
passes the word on to every open page, which then reloads just what it shows.
"""
import threading

_condition = threading.Condition()
_version = 0


def changed():
    global _version
    with _condition:
        _version += 1
        _condition.notify_all()


def version():
    return _version


def wait(seen, timeout):
    """Block until the version moves past seen, or timeout passes. Returns the current version."""
    with _condition:
        _condition.wait_for(lambda: _version != seen, timeout)
        return _version
