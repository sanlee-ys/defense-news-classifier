# Classes vs Functions — When to Reach for Each

> **📎 Paired note — keep in sync.** Twin lives in the **notes-api** repo:
> [`docs/notes/java-oop-and-ctors.md`](https://github.com/sanlee-ys/notes-api/blob/main/docs/notes/java-oop-and-ctors.md).
> These two teach one lesson from two sides (Python ↔ Java) — **edit one, update the other**
> so they don't drift.
>
> Personal OOP refresher, grounded in *this* repo's code. The Java twin shows the *other*
> half — where classes are the right call. Read them together; the lesson is the contrast,
> not either side alone.

## The one idea

A **function** is a verb: data goes in, a result comes out, nothing is remembered.
A **class** is a noun: a thing that **holds state** and **owns the behavior** that acts on
that state. You reach for a class when you have all three of:

1. **State worth keeping** — values that live longer than one call,
2. **Invariants to protect** — rules about what a *valid* instance looks like,
3. **Behavior bound to that state** — methods that only make sense given the data.

If you don't have those, a function is the honest tool. Our generator doesn't have them —
so it's functions. The `notes-api` `Note`/`NoteService` *do* — so they're classes.

## Why the generator is functions, not a class

[`src/generate.py`](src/generate.py) is **constants + two functions**, no class:

- `generate_combo(client, category, domain) -> list[dict]` ([generate.py:58](src/generate.py:58))
- `main()` ([generate.py:96](src/generate.py:96))

That's correct, not lazy. `generate_combo` is a **pure-ish transform**: hand it a
`(category, domain)` pair, it hands back a list of articles and forgets you existed. There's
no long-lived thing to *be* — no "a Generator" that persists between calls, no invariant
that could be violated. Wrapping this in a class would just be a function wearing a costume.

## The smell: a dict pretending to be an object

Look at the row we build for each article ([generate.py:129](src/generate.py:129)):

```python
rows.append({
    "id": article_id,
    "text": article["text"],
    "category": article["category"],
    "operational_domain": article["operational_domain"],
})
```

That dict has a **fixed shape** — always those four keys — but nothing enforces it. Typo
`"category"` and Python shrugs until something breaks three steps later. This is exactly the
case Java's `NoteRequest` **record** solves (your own comment there calls it "a frozen
`@dataclass`"). The Python mirror:

```python
from dataclasses import dataclass

@dataclass
class Article:
    id: int
    text: str
    category: str
    operational_domain: str
```

Now `Article(id=0, text="...", category="air")` **fails immediately** — `operational_domain`
is missing. That generated `__init__` is doing the same job as Java's
`public Note(String title, String content)` constructor: **refuse to create a half-built
object.** That's the "why" behind constructors in one line.

## When the generator *would* earn a class

The tipping point is shared state. Right now `client`, `MODEL`, the retry/sleep logic, and
`OUTPUT_PATH` are passed around or read as module globals. Bundle them and you have a real
object:

```python
class DatasetGenerator:
    def __init__(self, client, model=MODEL, out_path=OUTPUT_PATH):
        self.client = client          # set once, reused by every method
        self.model = model
        self.out_path = out_path

    def generate_combo(self, category, domain): ...   # uses self.client
    def run(self): ...                                # the old main()
```

`__init__` **is Python's constructor** — the setup ritual that runs on `DatasetGenerator(...)`
and leaves the object ready to use. It's the direct counterpart to the Java ctors, and to
`NoteService(NoteRepository repository)` constructor injection: the dependency (`client`) is
supplied once at birth instead of threaded through every call. We don't need this *yet* —
but the day we add a second model or a config knob, that's the signal.

## TL;DR

| Question | Answer | Seen in |
|---|---|---|
| Function or class? | Class only with **state + invariants + bound behavior**; else function | — |
| Why generator = functions | Stateless transform; nothing to hold or protect | [generate.py:58](src/generate.py:58) |
| What's a constructor *for* | Refuse to build an invalid/half-formed object | Java `Note(title, content)` |
| Python's constructor | `__init__` — runs on `ClassName(...)`, sets up the instance | example above |
| When a dict should be a class | Fixed-shape data passed around → `@dataclass` (≈ Java record) | [generate.py:129](src/generate.py:129) |
| When `generate.py` earns a class | Once `client`/`model`/config become shared state | example above |
