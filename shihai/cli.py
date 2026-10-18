# -*- coding: utf-8 -*-
"""识海 CLI —— 一个可被 agent 直接调用的记忆钩子。

用法(演示):
    python -m shihai.cli --db shihai.db seed         # 灌入种子经历
    python -m shihai.cli --db shihai.db ask "直播 担心"
    python -m shihai.cli --db shihai.db tick --days 30
    python -m shihai.cli --db shihai.db persona
    python -m shihai.cli --db shihai.db tell "我又搞砸了" --self

设计要点: 每条命令的输出都是给"人看的一小段"或给"模型看的结构化上下文",
两者都不大, 可以直接塞进 prompt。
"""

import argparse
import json
import sys

from .store import Store
from .ingest import Ingestor, Observation
from .recall import RecallEngine, Cue
from .lifecycle import Lifecycle
from .persona import PersonaEngine, diff, TRAIT_LABEL


def build(db):
    store = Store(db)
    life = Lifecycle(store)
    return store, Ingestor(store, lifecycle=life), RecallEngine(store), life, PersonaEngine(store)


def cmd_tell(args):
    store, ing, _, _, _ = build(args.db)
    obs = Observation(text=args.text, modality="self" if args.self else args.modality,
                      session=args.session)
    ev = ing.ingest(obs, importance_hint=args.importance)
    print("event #%d  节点:%s  任务:%s" % (
        ev.event_id,
        ", ".join("%s:%s" % (n["kind"], n["label"]) for n in ev.nodes) or "无",
        ev.task or "无",
    ))
    store.close()


def cmd_ask(args):
    store, _, eng, _, _ = build(args.db)
    cue = Cue(text=args.query, person=args.person, theme=args.theme,
              state=args.state, task=args.task, time_hint=args.time)
    hits = eng.recall(cue, limit=args.limit)
    if not hits:
        print("(没有记忆被点亮)")
    for h in hits:
        print("%-6s %5.3f  %s" % ("核心" if h.core else "普通", h.score,
                                  h.summary.replace("\n", " ")[:60]))
        print("         入口:%s  强度:%.2f  情绪:%s" % (
            "/".join(h.via) or "-", h.strength, h.emotion))
    store.close()


def cmd_tick(args):
    store, _, _, life, pers = build(args.db)
    rep = life.tick(days=args.days, persona=(None if args.no_persona else pers))
    print("衰减:%d  进入沉寂:%d" % (rep.decayed, rep.dormant))
    if rep.promoted:
        print("升格为核心记忆:")
        for eid, s in rep.promoted:
            row = store.get_event(eid)
            print("  #%d %.3f  %s" % (eid, s, row["summary"][:50]))
    if rep.distilled:
        print("蒸馏为稳定事实:")
        for theme, claim, sid in rep.distilled:
            print("  [%s] %s -> semantic#%d" % (theme, claim, sid))
    if rep.persona_changed:
        if "__first__" in rep.trait_delta:
            print("首次生成人格快照")
        else:
            print("人格发生变化:" + ", ".join(
                "%s %+.3f" % (TRAIT_LABEL.get(k, k), v) for k, v in rep.trait_delta.items()))
    store.close()


def cmd_persona(args):
    store, _, _, _, pers = build(args.db)
    snap = store.last_persona()
    if snap is None:
        card = pers.refresh()
        print(card.card)
    else:
        print(snap["card"])
        rows = store.conn.execute(
            "SELECT * FROM persona_snapshot ORDER BY id DESC LIMIT 2").fetchall()
        if len(rows) >= 2:
            d = diff(rows[1], rows[0])
            if d:
                print("\n最近一次漂移:" + ", ".join(
                    "%s %+.3f" % (TRAIT_LABEL.get(k, k), v) for k, v in d.items()))
    store.close()


def cmd_stats(args):
    store, _, _, _, _ = build(args.db)
    c = store.conn
    print("原始日志 %d 条" % c.execute("SELECT COUNT(*) FROM raw_log").fetchone()[0])
    print("事件     %d 条(核心 %d / 沉寂 %d)" % (
        c.execute("SELECT COUNT(*) FROM events").fetchone()[0],
        c.execute("SELECT COUNT(*) FROM events WHERE core=1").fetchone()[0],
        c.execute("SELECT COUNT(*) FROM events WHERE dormant=1").fetchone()[0]))
    print("节点     %d 个" % c.execute("SELECT COUNT(*) FROM nodes").fetchone()[0])
    print("关联边   %d 条" % c.execute("SELECT COUNT(*) FROM edges").fetchone()[0])
    print("语义     %d 条" % c.execute("SELECT COUNT(*) FROM semantic").fetchone()[0])
    print("召回记录 %d 次" % c.execute("SELECT COUNT(*) FROM recall_log").fetchone()[0])
    store.close()


def cmd_context(args):
    """给模型看的上下文块: 人格卡 + 当前被点亮的记忆 + 未完成任务。

    这是把识海接进 agent 的实际形状: 每次请求前注入这一块,
    agent 的行为自然带上"经历过这些"的偏差。
    """
    store, _, eng, _, pers = build(args.db)
    snap = store.last_persona()
    if snap is None:
        card = pers.refresh().card
    else:
        card = snap["card"]
    hits = eng.recall(Cue(text=args.query or ""), limit=args.limit)
    tasks = store.open_tasks()

    parts = ["## 我是谁", card, "", "## 此刻想起来的"]
    parts += ["- [%s] %s" % ("核" if h.core else "常", h.summary) for h in hits] or ["- (无)"]
    if tasks:
        parts += ["", "## 我还欠着"]
        parts += ["- %s%s" % (t["title"], "(截止 %s)" % t["due"] if t["due"] else "")
                  for t in tasks]
    text = "\n".join(parts)
    if args.json:
        print(json.dumps({"persona": card, "recalled": [h.summary for h in hits],
                          "tasks": [t["title"] for t in tasks]}, ensure_ascii=False, indent=2))
    else:
        print(text)
    store.close()


def main(argv=None):
    p = argparse.ArgumentParser(prog="shihai")
    p.add_argument("--db", default="shihai.db")
    sub = p.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("tell", help="输入一段经历")
    t.add_argument("text")
    t.add_argument("--self", action="store_true", help="这条经历是 agent 自己的, 不是外部世界")
    t.add_argument("--modality", default="text")
    t.add_argument("--session", default="cli")
    t.add_argument("--importance", type=float, default=None)
    t.set_defaults(func=cmd_tell)

    a = sub.add_parser("ask", help="按线索召回记忆")
    a.add_argument("query", nargs="?", default="")
    a.add_argument("--person")
    a.add_argument("--theme")
    a.add_argument("--state")
    a.add_argument("--task")
    a.add_argument("--time", dest="time")
    a.add_argument("--limit", type=int, default=5)
    a.set_defaults(func=cmd_ask)

    k = sub.add_parser("tick", help="推进一轮遗忘/巩固/升格")
    k.add_argument("--days", type=float, default=1.0)
    k.add_argument("--no-persona", action="store_true")
    k.set_defaults(func=cmd_tick)

    s = sub.add_parser("persona", help="打印人格卡")
    s.set_defaults(func=cmd_persona)

    st = sub.add_parser("stats", help="统计")
    st.set_defaults(func=cmd_stats)

    c = sub.add_parser("context", help="输出可注入模型的上下文块")
    c.add_argument("query", nargs="?", default="")
    c.add_argument("--limit", type=int, default=4)
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_context)

    args = p.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
