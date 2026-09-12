---
description: >-
  Every dashboard view is a URL: filters write themselves into the address bar, so sharing a view is copying a link rather than a feature to build.
---

# Saved views and shareable links

Every view in this dashboard is a URL. `#/contract?sev=ERROR` is the page and
its filters, and every filter change writes itself into the address bar — so a
view is shareable by copying the link, with no feature needed.

Saved views are the other half: a name for a link you want back.

## What a saved view stores

A name and the hash route. Nothing else.

The URL already carries the whole view, so storing anything more would be a
second representation of the same state — and the two would disagree the first
time a filter was added.

The default name is the page plus its filters (`contract · sev=ERROR`), because
"contract" and "contract filtered to errors" are two different views and a list
where both are called "contract" is worse than no list. Saving a second view
under an existing name replaces it, for the same reason.

## Where they live, and what that costs

**This browser.** Not the server, not your account, not your other laptop.

That is a real limitation and the panel says so rather than letting you find out
by opening the dashboard somewhere else:

> Saved in this browser only. Share a view by copying its link.

Every entry in the list is a real `<a href="#/…">`, so middle-click opens a tab
and right-click copies the link. The link is the shareable form of a view; the
list is not shareable at all.

## When storage refuses

A private window, blocked site data, a full quota. `localStorage` does not
merely come back empty in those cases — the accessor itself throws.

So every read and write is guarded, and the two failures are handled
differently:

- **A read that fails** gives an empty list. The dashboard keeps working; a
  convenience feature is not worth taking a page down for.
- **A write that fails** is reported in the panel — *"this browser is not
  storing site data, so nothing was kept"*. Saying nothing is how somebody
  finds out on their next visit that what they saved was never saved.

A stored value this feature did not write — hand-edited, or left by something
else at that key — is discarded rather than crashing the read, and entries
within a valid list that are not views are dropped individually.

## Limits

Twenty. Beyond that the list stops being a shortcut and becomes a second
navigation menu; the oldest is dropped. Names are trimmed and capped at sixty
characters.
