# FastAPI + Docker — Plain-English Walkthrough

> Personal notes explaining what the FastAPI service + Docker work
> ([PR #10](https://github.com/sanlee-ys/defense-news-classifier/pull/10)) actually is,
> in plain language.

## The big picture

This project is a **robot that reads a defense-news blurb and slaps two labels on it** —
*what it's about* (e.g. `procurement`) and *which battlefield* (e.g. `air`). That robot
already existed as a **script**: you run it, it reads, it prints labels, it stops.

Everything in this round was about turning that "run-it-and-it-stops" script into
something that can **stay open for business and answer questions all day**.

## 1. What's a "service" / API?

Think of the script as a **chef who cooks one meal then goes home**. A **service** is the
same chef, but now sitting behind a **drive-thru window that never closes**.

- You drive up and shout an order → a **request**
- The chef cooks and hands food back → a **response**
- The window itself (menu + speaker box) → the **API**

That's all `src/api.py` is — a drive-thru window bolted onto the robot. Two windows:

- **`/health`** — knock, and it says "yep, I'm awake." Cheap, cooks nothing. Used to check
  the chef hasn't fainted.
- **`/classify`** — hand it a news blurb, it hands back the two labels.

Built with **FastAPI**. It also has a **bouncer**: hand it an empty note or a 50-page novel
and it politely refuses (error `422`) instead of wasting the chef's time.

## 2. What's Docker?

The classic problem: *"it works on my computer but breaks on yours."* Different computers
have different stuff installed.

**Docker** fixes this by sealing the chef, kitchen, ingredients, and recipe into **one
lunchbox** (a **container**) that runs identically anywhere — your laptop or a big cloud
computer.

- **`Dockerfile`** — the recipe for packing the lunchbox: start with a small clean kitchen,
  install these tools, copy in the robot, open the window.
- Kept **lean**: did *not* pack the heavy `pandas` tool, because the drive-thru doesn't need
  it (that's only for grading tests).
- **`.dockerignore`** — the "don't pack this junk" list; keeps secrets and test data **out**
  of the lunchbox.

## 3. The Git branch stuff

Git = **save-points** for code. Branches = **parallel sketchbooks**, so you can try things
without scribbling on the good drawing.

- A **spike** = a quick "let me just see if this works" sketch. *Meant to be thrown away.*
  This one proved the drive-thru idea works.
- The snag: the spike was drawn on an **old, outdated page** (`master`). The real up-to-date
  drawing was on a different page (`main`) with all the newer work (tests, docs).
- The fix: instead of gluing the old sketch over the good drawing (which would have **erased**
  the newer stuff), we traced just the **4 new files** onto a fresh page off `main` — the
  `feature/fastapi-service` branch.

## 4. What's a Pull Request (PR)?

A PR is **"hey, can we add my sketch to the real drawing?"** — posted on a bulletin board so
you can look before it's glued down. **PR #10** is that. Nothing changes on `main` until
**you** click merge.

## 5. Why `master` had to go

Two "official" pages by accident — `master` (old) and `main` (current) — is a trap: someone
(or some robot) eventually builds on the wrong one. That's exactly what bit the spike.
Deleting `master` leaves **one source of truth**.

---

## TL;DR

We gave the one-shot robot a **24/7 drive-thru window** (FastAPI), sealed it in a
**ship-anywhere lunchbox** (Docker), and filed the paperwork to add it the **clean way**
(PR #10), while tidying up a confusing duplicate-page mess (`master`).

### The 4 files, one line each

| File | What it is |
|---|---|
| `src/api.py` | the drive-thru window (HTTP service) |
| `requirements-api.txt` | the short shopping list for the lunchbox (no `pandas`) |
| `Dockerfile` | the recipe for packing the lunchbox |
| `.dockerignore` | the "don't pack this junk" list |
