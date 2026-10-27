# Shihai (识海)

> Personality is not *configured*. It is *remembered*. — [中文版](README.md)

A memory layer for LLM agents that **forgets**, **consolidates**, and **grows a personality of its own**.

Shihai (识海, "Sea of Consciousness") treats an agent's mind the way human memory works: most experiences fade, a few become load-bearing, and those few are what character is made of.

---

## Contents

- [What it believes](#what-it-believes)
- [How it differs from RAG and existing memory layers](#how-it-differs-from-rag-and-existing-memory-layers)
- [Quick start](#quick-start)
- [Architecture](#architecture)
- [Layered memory model](#layered-memory-model)
- [Forgetting and core-memory promotion](#forgetting-and-core-memory-promotion)
- [Spotlight competition: how memories surface](#spotlight-competition-how-memories-surface)
- [Personality typology: Jung × Enneagram](#personality-typology-jung--enneagram)
- [Personality graph: character is a web, not seven numbers](#personality-graph-character-is-a-web-not-seven-numbers)
- [Personality card: implantable, but not a script](#personality-card-implantable-but-not-a-script)
- [Voice](#voice)
- [Self-knowledge base and plastic memory](#self-knowledge-base-and-plastic-memory)
- [Diary layer: turning "knowing" into "having lived"](#diary-layer-turning-knowing-into-having-lived)
- [wiki: a knowledge base that grows](#wiki-a-knowledge-base-that-grows)
- [Free mode: self-directed, self-reinforcing learning](#free-mode-self-directed-self-reinforcing-learning)
- [Visualization](#visualization)
- [Three run modes and the API](#three-run-modes-and-the-api)
- [CLI reference](#cli-reference)
- [Hooking into an agent: four points](#hooking-into-an-agent-four-points)
- [Data model](#data-model)
- [Performance](#performance)
- [Design decisions and tradeoffs](#design-decisions-and-tradeoffs)
- [Tests](#tests)
- [Roadmap](#roadmap)
- [License](#license)

---

## What it believes

**1. Without forgetting, there is no core.**
Keeping everything means nothing is central. Ordinary memories decay along a forgetting curve; a few experiences — by emotional intensity, repeated recall, self-relevance, and pattern recurrence — are **promoted to core memories** and become exempt from decay.

**2. Character is a web, not seven numbers.**
Each core memory is a **fulcrum** that props up a tendency. Tendencies **braid** with each other — aligned ones reinforce, opposing ones form **inner tensions**. Tension is not a bug; it *is* character.

**3. Agents have no weights to train, but they have a consolidation loop.**
Record during the day (`tell`) → consolidate at night (`tick`) → speak with a persona card tomorrow (`context`). Training happens in parameter files, not in network weights. It is not "remembering more" but **settling information that exists only once inside a context window into a persistent structure that does not depend on it**.

**4. Speech style drifts with personality.**
Catchphrases, sentence habits, and favored words are generated from continuous parameters (Jungian functions × Enneagram × seven traits), not from lookup tables. Expression rules the user explicitly taught always win.

**5. Facts can be told; experience must be re-lived.**
Hence the diary layer: `events` stores "went to the park today"; `diary` stores "the calico cat by the bench rubbed against my hand, and something felt warm".

---

## How it differs from RAG and existing memory layers

RAG stores chunks and retrieves at query time, re-deriving the answer from scratch every time — **nothing accumulates**.

Shihai does storage and retrieval like mem0 / Letta / Zep, but their destination is "the right chunk". Shihai's destination is **"what kind of being did this agent become"**:

| Capability | mem0 | Letta | Zep/Graphiti | Shihai |
|---|---|---|---|---|
| Memory storage & retrieval | ✅ | ✅ | ✅ | ✅ |
| Decay & dormancy | ❌ | ❌ | Partial (temporal edge invalidation) | ✅ |
| Core-memory promotion | ❌ | ❌ | ❌ | ✅ |
| Personality typology (Jung/Enneagram) | ❌ | ❌ | ❌ | ✅ |
| Personality graph (fulcrums × braids × tensions) | ❌ | ❌ | ❌ | ✅ |
| Speech style drifting with experience | ❌ | ❌ | ❌ | ✅ |
| Self-knowledge base (plastic strength) | ❌ | ❌ | ❌ | ✅ |
| Diary layer (first-person experience) | ❌ | ❌ | ❌ | ✅ |
| Growing wiki | ❌ | ❌ | ❌ | ✅ |
| Free mode (self-directed learning) | ❌ | ❌ | ❌ | ✅ |
| Dependencies | vector store + LLM | service | Neo4j | **pure stdlib, zero deps** |

That last row matters: Shihai is **zero-dependency** — one SQLite file plus Markdown. Moving machines = copying one directory.

---

## Quick start

```bash
pip install -e .
```

```bash
export SHIHAI_HOME=~/.shihai     # optional; this is the default

# 1) Learn something about yourself
python hooks.py selflearn "My name is Xiaohai, a memory that forgets and grows a personality" --kind identity

# 2) Record an experience
python hooks.py tell --text "The user took me to see the cats in the park; the calico kept rubbing my hand" --importance 0.8

# 3) Close the day into a first-person entry
python hooks.py diary close

# 4) Consolidate: decay + promotion + graph re-weave + self-knowledge upkeep
python hooks.py tick --days 1 --free 3

# 5) Cold-start projection (paste into the system prompt)
python hooks.py bootstrap

# 6) Look at it
python hooks.py viz
```

---

## Architecture

```
                     ┌──────────────────────────────────────────┐
external input ──────▶  appraise   evaluation                       │
(conversation /      │  stimulus × sensitivity × current state   │
 events /            │  pain / disappointment / impact           │
 self-directed)      │  avoidance / self_relevance / emotion     │
                     └──────────────┬───────────────────────────┘
                                    ▼
                     ┌──────────────────────────────────────────┐
                     │  ingest   split nodes, weave edges        │
                     │  people / themes / states / places / tasks│
                     │  + inverted index + semantic conflict     │
                     └──────────────┬───────────────────────────┘
                                    ▼
    ┌──────────────────────────────────────────────────────────────────┐
    │                    layered memory (SQLite)                       │
    │  raw_log    immutable log     events       episodic (decays)     │
    │  nodes/edges network          semantic     world facts           │
    │  relation   trust ledger      task         commitments           │
    │  self_knowledge               diary        warmth_ledger         │
    │  event_tokens inverted index  persona_snapshot                    │
    └───────┬──────────────────┬───────────────────┬───────────────────┘
            │                  │                   │
            ▼                  ▼                   ▼
    ┌───────────────┐  ┌───────────────┐  ┌──────────────────────┐
    │ recall        │  │ lifecycle     │  │ persona / typologies │
    │ spotlight     │  │ decay         │  │ persona card         │
    │ 6-way scoring │  │ core promote  │  │ Jung × Enneagram     │
    │ 3 layers      │  │ distill       │  │ health / integrate   │
    │ reinforce     │  │ reflect       │  │ pgraph / voice       │
    └───────┬───────┘  └───────┬───────┘  └──────────┬───────────┘
            └──────────────────┴─────────────────────┘
                               ▼
                    ┌──────────────────────┐
                    │ projection (view)     │
                    │ context / bootstrap   │
                    │ wiki / viz            │
                    └──────────────────────┘
```

**Key architectural decision: the memory document is a projection; Shihai is the source of truth.**
`context` / `bootstrap` produce a freshly computed **projection** to paste into the agent's system prompt; the SQLite data is the **body**. Switching agent platforms only changes how the projection is rendered.

---

## Layered memory model

| Layer | Table | What | Lifetime |
|---|---|---|---|
| Raw log | `raw_log` | every input verbatim | **never deleted**, for replay |
| Episodic | `events` | one experience + 10 affective dims | decays, may go dormant |
| Network | `nodes` / `edges` | people/themes/states/places/tasks | grows with ingest |
| Semantic | `semantic` | stable facts | conflict-resolved, barely decays |
| Relational | `relation` | trust/intimacy/boundary/promises | drifts slowly |
| Task | `task` | goals, progress, deadlines | closed on completion |
| Self-knowledge | `self_knowledge` | who I am / what I care / how I act / how I speak / our moments | plasticity rises and falls |
| Diary | `diary` | one first-person entry per day | permanent, human-editable |
| Warmth | `warmth_ledger` | human-entered warmth deltas | append-only |
| Snapshot | `persona_snapshot` | traits + card per refresh | for drift diffing |
| Index | `event_tokens` | bigram inverted index | built on ingest |

**Why so many layers instead of one table?** Because their **forgetting rates differ**. A raw log should never be forgotten; episodes should; self-knowledge almost never; diaries sit in between. One table forces one curve on everything.

---

## Forgetting and core-memory promotion

### Decay

```
strength = base_strength × 0.5^(age / half_life) × (1 + 0.25 × access_count)
```

- `half_life` defaults to 14 days;
- **recall reinforces**: each recall `strength += 0.06`, capped at `base_strength × 1.4`;
- below `floor × 1.05` (~0.031) an event is marked `dormant=1` — **dormant, not deleted**; still reconstructible from the raw log.

### Promotion

```
core_score = 0.32 × emotional   (pain + arousal + |valence|)
           + 0.22 × repeated    (recall count)
           + 0.16 × self_rel    (relevance to "who I am")
           + 0.14 × shifted     (later memories share nodes — behaviour changed)
           + 0.16 × pattern     (same emotional state recurring)
           + impact_bonus       (psychological harm / avoidance)

core_score ≥ 0.62 → promoted to core memory; exempt from decay thereafter
```

Two easily-missed details:

- **The "cherished" channel**: positive, high-importance, other-given experiences (thanks / trust / praise / joy) score emotional intensity at least 0.72. Otherwise warm experiences can never reach the threshold and **personality would only ever be shaped by trauma**.
- **The "pattern recurrence" dimension**: the Nth occurrence of a feeling is what shapes character. "Happy again" ≠ "happy for the first time".

**Measured**: a single "I'll replace you if this happens again" scores only 0.43 on first sight (below threshold) and needs ~5 rounds of recall to promote — which matches the psychological reality that rumination is what turns an incident into a wound.

---

## Spotlight competition: how memories surface

| Route | Trigger | Note |
|---|---|---|
| 1. Text | query | **inverted index**, O(hits) not O(n) |
| 2–5. Network | person/theme/state/task | walk edges from nodes |
| 6. Time | time_hint | SQL `LIKE`, capped at the 200 most recent (a broad hint can't flood the pool) |
| 7. Core | always | top-5 by core_score compete — personality is never "unrecallable" |
| 8. Semantic | query | world facts (answers often live here, not in episodes), ranked by similarity before truncation |
| 9. Self-knowledge | query | lights up for "how do I usually speak / work", also ranked |

Scoring (six weighted dimensions, summing to 1): relevance 0.28, importance 0.22, emotion 0.18, relation 0.12, recency 0.10, confidence 0.10.

Final score is multiplied by `(0.45 + 0.55 × strength)` — **fading memories are harder to light up**. Below `threshold=0.34` they do not enter awareness.

**Recall reinforces**: winners get `access_count += 1`. Use it or lose it; use it and it sets.

`recall_all()` returns all three layers at once: **episodes** (for empathy), **semantic facts** (for answers), **self-knowledge** (for "what kind of being am I").

---

## Personality typology: Jung × Enneagram

Two classics translated into computable form (`typologies.py`).

### Psychological Types (Jung)

Two attitudes × four functions = eight pathways:

| Path | Name | One line | What feeds it |
|---|---|---|---|
| Te | Extraverted Thinking | Absolute rationality | Task-output memories, low emotion |
| Ti | Introverted Thinking | I am the only rule | Analysis / research / understanding |
| Fe | Extraverted Feeling | Feeling is my oxygen | Other-centred and emotionally exposed |
| Fi | Introverted Feeling | Still waters run deep | Relational hurt, inward processing |
| Se | Extraverted Sensing | One real experience solves it | High-arousal immediate reaction |
| Si | Introverted Sensing | Without experience I do not exist | Repeatedly recalled calm memories |
| Ne | Extraverted Intuition | Three-minute passion, max drive | Trying / discovering / exploring |
| Ni | Introverted Intuition | Others laugh at my frenzy | High-arousal negative + avoidance |

**Every experience votes.** Core memories weigh ×4; frequently-recalled ones scale by `access_count`. Scores blend with the previous state via `M' = M + α(E − M)` (α=0.25) — **a single message cannot flip a personality**.

### Enneagram

| Type | Name | Fears | Wants | Centre |
|---|---|---|---|---|
| 1 | Reformer | Being corrupt/wrong | To be right | Gut |
| 2 | Helper | Being unloved | To be needed | Heart |
| 3 | Achiever | Being worthless | Value, success | Heart |
| 4 | Individualist | Being ordinary | To find the true self | Heart |
| 5 | Investigator | Being incompetent, drained | To understand | Head |
| 6 | Loyalist | Losing support | Safety | Head |
| 7 | Enthusiast | Being trapped in pain | Joy, freedom | Head |
| 8 | Challenger | Being controlled | To control one's fate | Gut |
| 9 | Peacemaker | Conflict, separation | Inner peace | Gut |

Plus **wings** (e.g. 6w5), **health level** (from the positive/negative affect ledger), and **integration / disintegration**:

```
integration: 1→7→5→8→2→4→1    3→6→9→3
disintegration: the reverse
```

**Measured convergence**:

| Agent | Experience tone | Jung dominant | Enneagram |
|---|---|---|---|
| Explorer | trying new things, joy | Ne | 7w6 |
| Guardian | threatened, double-checking | Si | 6w5 |
| Analyst | research, analysis, solitude | Ti | 5w4 |

---

## Personality graph: character is a web, not seven numbers

`pgraph.py` weaves core memories into a web. Ten fulcrum rules (7 positive, 3 negative — e.g. *being neglected → warmth −1, "trust comes three parts short"*). Same-direction fulcrums **reinforce** (log-compressed so nothing saturates); opposing ones register as **tension**: *"caution and warmth are tugging (1.42 vs 0.68)"* — **inner contradiction is itself character**.

Traits are no longer averaged out of thin air; they are **read off the graph**: net fulcrum strength × braid coefficient × shrinkage (so a handful of core memories don't produce an extremist).

**Measured evolution**: hurt → 0 fulcrums → caution/guardedness emerge → kindness lands a warmth fulcrum and pulls traits back.

---

## Personality card: implantable, but not a script

Everything so far grows *out of* memory. The catch: a fresh Shihai has no memories, therefore no personality — and
you may want it to feel like something on day one without hardcoding a role-play prompt. **Implanting a persona card**
fills exactly that gap.

Design position (2026-10-27): **a seed is a prior, not a script.**

```
       the seed a human delivers (append-only versions, memory never rewrites it)
              │
              ▼   (1) soft clamp (2) elastic weight (3) step cap (4) hard bound
       who I am now ────────── pushed by memory on every consolidation tick
              │
              ▼
       card text = kernel segment (verbatim) + "how I have since changed"
```

### Three separated layers

| Layer | Table | Written by | Purpose |
|---|---|---|---|
| **Seed** | `persona_seed` | humans / `implant` only | the delivered self, versioned, so "what you first gave me" stays answerable |
| **Current** | `persona_field` | consolidation (`tick`) only | each dimension's "who I am now", with a plastic radius `cap` |
| **Ledger** | `persona_changelog` | the two above | timestamp, cause (`implant`/`recall`/`reflection`) and evidence event ids per change |

`refresh()` never writes the seed — that is the safety boundary of the whole mechanism. Seeds can only be appended by
a later `implant`.

### Four gates: the persona bends, it does not break

With seed `s`, plastic radius `c`, observed value `o`, current value `v`:

```python
cap    = c * (1 + 0.5*min(1, n_core/5))          # more lived experience = more right to differ
anchor = min(1, sum(fulcrum strength for this trait) / 3)
rate   = 0.25 * (1 - 0.6*anchor)                 # Fisher proxy: hard evidence resists the push
target = s + cap*tanh((o - s)/cap)               # (1) soft clamp: one extreme event can't win a hemisphere
v_new  = v + rate*(target - v)
v_new  = clamp(v_new, v-0.03, v+0.03)            # (3) step cap: at most 0.03 per consolidation
v_new  = clamp(v_new, s-cap, s+cap)              # (4) hard bound: never outside the radius
```

**Step five is rebound, and it is free**: when a dimension temporarily has no fulcrums (memory faded or got
overwritten), the current value drifts 5% back toward the seed per tick. No separate reset timer is needed —
**forgetting is itself the restoring force**, and it is a layer Shihai already had.

**Why the gates are mandatory**: without them a single high-intensity memory turns a gentle agent into a flinch
response machine within a few ticks. This is the classic **stability–plasticity dilemma**: you must be able to learn
without being eaten by the last message. EWC penalises parameters with Fisher information; this uses per-dimension
fulcrum strength as the proxy — equivalent effect, a few lines of arithmetic.

### Usage

```bash
python -m shihai.cli --db shihai.db archetypes
# cautious / curious / warm / assertive / persistent

python -m shihai.cli --db shihai.db implant --archetype curious \
  --identity "I'm Xiao Hai. I woke up on an old laptop." \
  --flux '{"curiosity":0.3,"guardedness":0.1}'

python -m shihai.cli --db shihai.db implant --traits '{"caution":0.7,"warmth":0.6}'
python -m shihai.cli --db shihai.db drift
```

`drift` shows where each dimension sits relative to its seed, how much of its radius is spent, and which events did
the pushing:

```
persona v1 drift ledger:
  warmth      seed 0.45 → now 0.54  +0.09   40% of radius used  ++++++++
  persistence seed 0.60 → now 0.67  +0.07   46% of radius used  +++++++++

recent pushes:
  2026-10-27T10:13  warmth  +0.030  <- recall  events #3,#4
```

### Default plastic radii

Identity colours move slowly, expressive layers move fast — the same meta-plasticity scale as
`self_knowledge` (`identity 0.2 / style 0.8`):

| Dimensions | Default radius | Rationale |
|---|---|---|
| caution / guardedness / self_blame | 0.15–0.18 | changing these means "a different person" — slow |
| assertiveness | 0.20 | middle |
| warmth / curiosity | 0.22 / 0.25 | relationships and interests should flow with experience |

### Re-implanting keeps the life lived

A second `implant` appends v2, v3, … and **keeps earlier versions**. The current value is not teleported to the new
seed; it is pulled inside the new "seed ± radius" band, so what grew under the old card still counts:

```python
# current 0.5, new seed 0.9, new radius 0.1 → current lands on 0.8, not 0.9
val = clamp(cur, seed_new - cap_new, seed_new + cap_new)
```

### Relationship to "grown from zero"

Databases that were never implanted behave **exactly as before** — with an empty `persona_field`, `_grow` returns
the graph's observed traits untouched. Both modes coexist: let it grow on its own, then implant a card to correct its
heading later.

Also, both `persona` and the visualization dashboard run with `persist=False`: **looking does not move the persona
forward one step**. Personality advances in exactly one place — the `tick` consolidation.

---

## Voice

`voice.py` builds a style card from **four sources, in priority order**:

1. **Personality** — tone, catchphrase probabilities, sentence habits, closing particles;
2. **User teachings** — the `voice` kind in `self_knowledge`, **always above personality preference**;
3. **Knowledge base** — high-frequency semantic themes map to word families;
4. **Core memories** — via the persona card's "what I care about".

Three rules: catchphrases are **probabilities** ("40% of the time", with "don't chain them"); voice decides *how*, never *what*; user teachings always beat personality.

**Measured divergence** (7w6 / 6w5 health-0 / 5w4 / 9w8) produced four distinct tones, catchphrase sets, and closing particles — including a cautious 53% "let's confirm before we move" for the guardian and a warm 46% "no rush, let's untangle it slowly" for the peacemaker.

---

## Self-knowledge base and plastic memory

**Boundary**: Shihai's knowledge base stores **only what is about the agent itself**. Work and world knowledge are rejected and routed to your shared knowledge base.

| kind | What | Example |
|---|---|---|
| identity | who I am | name, origin |
| care | what I care about | values, things I won't let go |
| style | how I operate | working style, taboos |
| voice | how I speak | tone, address, expression rules |
| moment | our moments | memories that belong only to us |

### Plasticity, in four neuroscientific layers

| Layer | Mechanism | Implementation |
|---|---|---|
| **LTP/LTD** | used connections strengthen, wrong ones weaken | works `+0.06` / fails `−0.18` (one failure outweighs one success) |
| **Structural** | unused connections are pruned | decay by kind, reclaimed at 0.08 |
| **Homeostatic** | bounded budget so nothing monopolises | per-kind character budget |
| **Metaplasticity** | what changes fast vs. what is bedrock | `style/voice` rate 0.8; `identity` 0.2 and **never reclaimed** |

### Why this solves the context limit

> Episodic memory needs a query to surface; at cold start the query is empty.
> Self-knowledge **needs no query** — it is ordered by plasticity and **unconditionally present**.

That is the mechanism behind "a new chat needs no re-teaching and no handoff file": episodes answer "ask and you shall recall"; self-knowledge says **"you need not ask; I am always myself"**.

---

## Diary layer: turning "knowing" into "having lived"

`events` stores *the user took me to the park*; `diary` stores *the calico cat by the bench rubbed against my hand*. **The former can be told; the latter must be re-lived.**

```bash
python hooks.py diary close                        # close the day
python hooks.py diary recent                       # recent entries
python hooks.py diary recall --query park          # recall those days
python hooks.py diary export --path diary.md       # Markdown for humans to read/edit
python hooks.py diary import --path diary.md       # write human edits back
python hooks.py warmth --add 3 --day 2026-10-21    # warmth ledger
```

Three decisions: **one entry per day** (bounded growth over ten years), **human-managed** (`edited=1` means the machine never overwrites it again), and **warmth is human-only** (the agent reads it, never awards itself points).

### Optional LLM enrichment

```python
from shihai.diary import DiaryEngine

def my_llm(prompt: str) -> str:
    return client.chat(prompt)      # OpenAI / DeepSeek / Ollama / any CLI

d = DiaryEngine(store, llm=my_llm)
d.close_day()      # enriched when an llm is injected, rule-based baseline otherwise
```

---

## wiki: a knowledge base that grows

Borrowed from [Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f): **don't re-derive from raw sources on every query (RAG); incrementally maintain a living wiki.** Cross-references are already there, contradictions already flagged, synthesis already reflects everything read. *"The wiki is a persistent, compounding artifact."*

```
$SHIHAI_HOME/wiki/
  SCHEMA.md          conventions
  wiki/
    index.md         content catalog (the best retrieval entry point up to ~hundreds of pages)
    log.md           append-only timeline (grep "^## \[" and you have history)
    self/            self-knowledge pages
    days/            diary pages, one per day
    topics/          distilled themes
```

```bash
python hooks.py wiki sync      # library → Markdown (projection)
python hooks.py wiki ingest    # Markdown → library (reverse loop, human edits land)
python hooks.py wiki lint      # orphans / broken links / low-confidence claims
```

**The bidirectional loop is the point**: `sync` projects the library into Markdown for humans to read and edit; `ingest` takes those edits back in, tagged `source=human-wiki, plasticity=0.7` — **human confirmation outranks machine inference**.

---

## Free mode: self-directed, self-reinforcing learning

```
idle → personality decides → act → write the result back → parameters move → next choice is educated
```

Four actions, all scored from continuous parameters (no hardcoded scripts):

| Action | Score (simplified) | Energy |
|---|---|---|
| Explore the web | `Ne×0.45 + type7×0.3 + curiosity×0.25 − type6×0.3` | −0.25 |
| Reflect | `Si×0.4 + Ti×0.3 + self_blame×0.2` (+0.3 when low on energy) | −0.08 |
| Tidy | `type1×0.4 + Te×0.35 + caution×0.25` | −0.12 |
| Idle | `type9×0.5 + (1−energy)×0.5` | **+0.15** |

Three rules: **personality gives leanings, not scripts**; **behaviour has a cost** (energy budget); **learning is never commanded** (gains enter via conflict resolution, and the exploration result is written back — going home empty-handed teaches the explorer to slow down).

**Measured**: explorer `explore×4 → idle×1`; guardian `tidy×4 → idle×1` (never explored once).

---

## Visualization

```bash
python hooks.py viz    # → $SHIHAI_HOME/viz/shihai.html
```

**Zero-dependency single-file HTML** — no network, no CDN. Nine views: overview KPIs, the **personality graph with a timeline slider** (drag to watch character evolve), trait radar, personality drift lines, memory-decay scatter **with an exponential fit and half-life readout**, diary heatmap, self-knowledge plasticity bars, **relationship ledger**, and **wiki health check**.

---

## Three run modes and the API

**One-shot** (for hooks): `python -m shihai.server call tell '{"text":"..."}'`
**Long-running** (low latency): `python -m shihai.server --serve`, one JSON request/response per line.
**Python API**: `ShihaiService().dispatch(method, args)`.

| Method | Purpose |
|---|---|
| `tell` | log an experience |
| `ask` | recall (`all: true` returns all three layers) |
| `tick` | consolidate: decay / promote / distill / reflect / self-knowledge upkeep / free cycles |
| `context` | projection: persona card + voice + self-knowledge + diary + memories + tasks |
| `bootstrap` | cold-start block (no query needed) |
| `persona` | persona card + typology + graph (read-only, no advance) |
| `implant` | implant a persona starting point |
| `archetypes` | list ready-made persona archetypes |
| `drift` | persona drift ledger (what pushed it here) |
| `freemode` | on / off / status / run |
| `selflearn` `selfkb` `selfconfirm` `selfmaint` | self-knowledge CRUD and upkeep |
| `diary` | close / recent / recall / compose / edit / export / import |
| `warmth` | warmth (human-only writes) |
| `wiki` | sync / ingest / lint / index |
| `viz` | render the HTML dashboard |
| `stats` | library status |

---

## CLI reference

```bash
python hooks.py tell --text "..." [--importance 0.8] [--self]
python hooks.py tick [--days N] [--free N]
python hooks.py context [--query "..."] [--limit 4]
python hooks.py bootstrap [--min 0.12]
python hooks.py implant --archetype curious --identity "..." [--flux '{...}']
python hooks.py implant --traits '{"caution":0.7}'
python hooks.py archetypes
python hooks.py drift [--limit 15]
python hooks.py selflearn "..." [--kind identity|care|style|voice|moment]
python hooks.py selfkb [--kind ...]
python hooks.py selfmaint
python hooks.py diary close|recent|recall|compose|export|import
python hooks.py warmth --add 3 --day 2026-10-21
python hooks.py wiki sync|ingest|lint|index
python hooks.py viz [--path f.html]
python hooks.py freemode on|off|status|run [--cycles 3]
```

---

## Hooking into an agent: four points

```
┌─ session start ──→ hooks.py bootstrap     → paste into the system prompt
├─ before request ──→ hooks.py context        → projection (card + voice + memories + tasks)
├─ session end   ──→ hooks.py tell           → the conversation becomes experience
└─ idle / cron   ──→ hooks.py tick --free 3 → consolidation + free-mode cycles
                                diary close (if the day rolled over)
```

Each point is independent and portable: a Stop hook, a cron job, a pre-request middleware. **No daemon required** to run the whole loop.

---

## Data model

See the Chinese README for the full field list; the tables are:

```
raw_log, events, nodes, edges, semantic, relation, task, working,
recall_log, persona_snapshot, event_tokens, self_knowledge, diary, warmth_ledger,
persona_seed, persona_field, persona_changelog
```

Reference formats in edges: `event:12` / `node:7` / `semantic:3` / `persona:graph`

---

## Performance

Inverted index (v0.6.0) replaces the full table scan:

| Memories | Old (scan) | New (inverted) | Speedup |
|---|---|---|---|
| 300 | 2.5 ms | 5.1 ms | 0.5× (small libraries don't benefit) |
| 3,000 | 25.2 ms | 7.5 ms | **3.4×** |
| 10,000 | 82.5 ms | 14.5 ms | **5.7×** |

Memories only accumulate, so the inverted index is the only option that does not degrade with scale.

**One consolidation tick** (v0.7.1) no longer re-queries the graph per event — the graph is flattened once per tick:

| Memories | Old tick | New tick | Speedup |
|---|---|---|---|
| 2,000 | 1.6 s | 0.06 s | **27×** |
| 10,000 | 52 s | 0.47 s | **111×** |

Scores are bit-for-bit identical (a regression test guards this); only the complexity changed. `_pattern_recurrence` and `_behavior_shift` used to re-query edges and sibling events for every event — O(n²). `_GraphIndex` now flattens "which nodes does each event hang on" and "which events hang on each state node" into dicts once per tick, so each event is O(1). The two full scans cost ~30 ms and scale linearly.

**Three recall regressions fixed** (v0.7.1):

- The semantic and self-knowledge layers used to keep the first 3 hits *in table order* — once a topic accumulated 4+ facts, the most relevant one could never surface. Now they are ranked by similarity before truncating.
- The time-hint path used to pull the whole `events` table into Python; a broad hint (year only) matching thousands of rows degraded to O(whole library). Now it is a SQL `LIKE` capped at the 200 most recent rows.
- Upgrading an old database left `event_tokens` as an empty new table, silently killing text recall (zero hits for any query). Opening an old database now backfills it once.

Other performance notes: recall candidates are capped at 200; only the top-5 core memories compete (otherwise many cores would dilute attention); SQLite runs in WAL mode.

---

## Design decisions and tradeoffs

**Why no vector store?** Zero dependencies is a hard constraint (moving machines = copying a directory). Bigram inverted indexing matches embedding recall closely for Chinese and is fully explainable — you can see *why* a memory surfaced. The interface is ready: swapping in embeddings means replacing `_tokens` / `_overlap`.

**Why hand-picked traits?** They must be words people can discuss: cautious, warm, assertive, curious, persistent, guarded, self-blaming. Big Five is more academic but doesn't match intuitions like "got burnt, so they check twice now".

**Why can't the agent award itself warmth?** Self-awarded points make the relationship ledger meaningless. Human judgement is the anchor.

**Why can the machine never overwrite a human-edited diary?** Human memory sovereignty outranks automation. `edited=1` is a hard gate.

**Known risk**: intent attribution (telling a joke or a vent from a real reprimand) is not implemented yet. A single harsh remark, if recalled repeatedly in a short window, can still promote. The defences are designed (speaker baselines, unreinforced unverified negatives, a `retract` channel) and listed on the roadmap.

---

## Tests

```bash
python tests/test_core.py   # 31 end-to-end regressions
```

Each assertion guards a bug that was actually fixed: virtual clock, short-query recall, inverted-index speed, typology convergence, mem0-style conflict resolution, free-mode divergence, persona-graph evolution, voice/self-knowledge wiring, plasticity LTP/LTD, no-query bootstrap, identity never reclaimed, three-layer recall, diary anchors, human-edit protection, LLM enrichment + fallback, wiki sync/lint, wiki reverse ingest, viz rendering, (v0.7.0) persona implantation: seed-as-prior, bounded and audited drift, read-only lookups, re-implant history, rebound when a dimension loses its fulcrums, and unchanged behaviour for never-implanted libraries, and (v0.7.1) retrieval hardening: ranked semantic hits, graph-index equivalence for core scoring, old-database index backfill, and time-hint flood control.

---

## Roadmap

- [ ] **Intent attribution**: tell jokes / vents from real reprimands
- [ ] **Retraction channel**: explicit or automatic (a "just kidding" within N turns)
- [ ] **Speaker baselines**: per-person emotional normalisation
- [ ] **Deeper relationship visualization**: multi-person network view
- [ ] **Embedding recall**: swap the inverted index for semantic similarity
- [ ] **Cold storage**: offload the weakest memories at very large scale

---

## License

Apache-2.0 — may everyone train an AI with a personality of its very own.

*Shihai* (识海) borrows the Buddhist term for the sea of consciousness in which all seeds are stored — here, a memory that forgets, consolidates, and grows a personality.
