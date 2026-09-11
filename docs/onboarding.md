# The onboarding tour

Four steps, once, on a first visit. Then never again — unless you ask.

## The failure a tour usually has

Pointing at something that is not there.

A step anchored to a selector that matches nothing leaves a highlight box at
the top-left corner and a caption describing a control the reader cannot see.
That is worse than not running at all, because it teaches them the tour is
lying about the interface it is supposed to be explaining.

So the steps are filtered against the document **before** anything renders:

- a step whose control is absent is dropped, not shown;
- the counter counts what survived, so "2 of 3" is three real steps;
- a tour with **no** surviving steps does not run — and is not marked as seen,
  because nothing was shown, nothing was learned, and marking it seen would
  spend the one chance it has.

## Dismissal, and when it cannot be recorded

The flag lives in `localStorage`, which can refuse: a private window, blocked
site data, a full quota.

If the write fails, the tour says so on the step you dismissed it from —
*"this browser is not storing site data, so this will show again next
visit"* — rather than silently reappearing every visit and leaving you to
conclude the dashboard is broken.

If the *read* throws, the tour is treated as already seen. An undismissable
tour that returns on every load is the worse of the two failures.

## Getting it back

**About → Take the tour again.** A tour that runs once and has no way back is
a tour nobody sees, because the people most likely to skip it in the first ten
seconds are the ones who later want it.

## Keyboard

| Key | |
|---|---|
| `→` | next step |
| `←` | previous step |
| `Esc` | dismiss |

Focus moves into the panel when it opens and returns to where it was when it
closes. Motion respects `prefers-reduced-motion` through the stylesheet's
existing reset.

## Empty states are the other half of this

A tour explains the controls. What explains a page with nothing on it is the
page itself, and the distinction that matters there is between **no findings**
(good news) and **this data source carries no findings section** (no news at
all). They render identically as a blank table, so the dashboard says which —
see `Empty` and `Missing` in `web/src/components/ui.tsx`, where the hint also
depends on whether the source is a live server or an artifact, because telling
somebody pointed at a server to regenerate a demo file sends them somewhere
that cannot help.
