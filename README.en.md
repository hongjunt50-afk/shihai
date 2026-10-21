# Shihai (识海)

> Personality is not *configured*. It is *remembered*. — [中文版](README.md)

A memory layer for LLM agents that **forgets**, **consolidates**, and **grows a personality of its own**.

Shihai (识海, "Sea of Consciousness") treats an agent's mind the way human memory works: most experiences fade away, a few become load-bearing, and those few are what character is made of.

## What it believes

- **Without forgetting, there is no core.** Keeping everything means nothing is central. Ordinary memories decay along a forgetting curve; a few experiences — by emotional intensity, repeated recall, self-relevance, and pattern recurrence — get **promoted to core memories** and become exempt from decay.
- **Personality is a graph, not seven numbers.** Each core memory is a *fulcrum* that props up a tendency. Tendencies *braid* with each other — aligned ones reinforce, opposing ones form **inner tensions**. Tension is not a bug; it *is* character.
- **Agents have no weights to train, but they have a consolidation loop.** Record during the day (`tell`) → consolidate at night (`tick`) → speak with a persona card tomorrow (`context`). Training happens in parameter files, not in network weights.
- **Speech style drifts with personality.** Catchphrases, sentence habits, and favored words are generated from continuous parameters (Jungian functions × Enneagram × seven traits). Rules the user explicitly taught always take precedence.

## Five-minute start

```bash
pip install -e .                      # pure standard library, zero dependencies

# Three hook points — this is the entire agent integration
python hooks.py tell   --text "The user praised me today; I'm happy"   # session end: log experience
python hooks.py tick   --days 1 --free 3                               # scheduled: consolidation + free-mode cycles
python hooks.py context --query "recent collaboration"                 # pre-request: project into memory doc
```

Long-running service mode (low latency):

```bash
python -m shihai.server --serve
# stdin:  {"method": "persona", "id": 1}
# stdout: {"ok": true, "result": {...}}
```

## Architecture

```
experience ─▶ appraise   evaluate (stimulus × sensitivity × state)
          ─▶ ingest     split into nodes; weave the network (people/themes/states/tasks)
          ─▶ recall     spotlight competition (six-way weighted; winners enter awareness and self-reinforce)
          ─▶ lifecycle  decay / promote to core / distill semantics / reflection trigger
          ─▶ typologies Jung's 8 functions × Enneagram — a computable translation of two classic books
          ─▶ pgraph     personality graph (fulcrums × braids × tensions)
          ─▶ voice      speech style (catchphrases / sentence habits / favored words)
          ─▶ freemode   free mode (self-directed exploration; gains written back)
          ─▶ persona    the persona card — a readable projection of everything above
```

All data lives under `SHIHAI_HOME` (default `~/.shihai`; set the env var to relocate).
Moving to a new machine = copying one directory.

## How it differs from mem0 / letta

| | mem0 / letta | Shihai |
|---|---|---|
| Memory storage & retrieval | ✅ | ✅ |
| Forgetting & core-memory promotion | ❌ | ✅ |
| Personality typologies (Jung / Enneagram) | ❌ | ✅ |
| Personality graph (web of fulcrums) | ❌ | ✅ |
| Speech style drifting with experience | ❌ | ✅ |
| Free mode (self-directed learning) | ❌ | ✅ |

## Self-knowledge base (plastic memory)

Shihai keeps its own knowledge base — but it **only stores what is *about me***:

| Kind | What | Example |
|---|---|---|
| identity | who I am | name, origin |
| care | what I care about | values, things I won't let go |
| style | how I operate | working style, taboos |
| voice | how I speak | tone, forms of address, expression rules |
| moment | our moments | memories that belong only to us |

**Work knowledge and world knowledge never enter Shihai** — those live in your shared knowledge base.

### Plasticity: the *strength* changes, that is what "plastic" means

```
works      plasticity +0.06   (LTP)
fails      plasticity -0.18   (LTD — one failure outweighs one success)
unused     decays by kind      (identity slowest at 0.2; style/voice 0.8)
at 0.08    reclaimed (identity is never reclaimed)
```

### Cold start: a new chat needs no re-teaching

```bash
python hooks.py bootstrap
```

Ordered by plasticity and **unconditionally present, with no query** — that is what makes it
different from episodic memory: episodes answer "ask and you shall recall", self-knowledge
says "you need not ask; I am always myself".

## Tests

```bash
python tests/test_core.py   # 7 end-to-end regressions: forgetting, typology convergence,
                            # conflict resolution, behavior divergence, graph evolution
```

## License

Apache-2.0 — may everyone train an AI with a personality of its very own.
