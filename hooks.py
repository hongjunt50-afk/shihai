# -*- coding: utf-8 -*-
r"""识海钩子脚本 —— 把识海接进 agent 日常循环的三个对接点。

架构(2026-10-18 定稿): 记忆文档是投影, 识海是本体, 钩子是血液循环。

    ┌─ 会话开始/请求前 ──→ hook.py context   产出注入块(写 stdout, 贴进记忆文档)
    ├─ 会话结束(Stop)  ──→ hook.py tell      把这次对话作为经历入库
    └─ 空闲/定时(cron) ──→ hook.py tick      固结 + 自由模式行为环

用法:
    python hooks.py context --query "今天的主题"     # 输出可注入的记忆文档块
    python hooks.py tell   --file last_session.txt   # 会话摘 要入库
    python hooks.py tell   --text "一句话经历"
    python hooks.py tick   [--days 1] [--free 3]     # 定时任务调用
    python hooks.py freemode on|off|run [--cycles 3]

每次调用独立进程, 调完即退 —— 不需要常驻服务也能跑通全链路;
常驻形态(python -m shihai.server --serve)供需要低延迟的框架使用。
"""

import argparse
import json
import sys

from shihai.server import ShihaiService
from shihai import home as H


def _render_context_block(r):
    """把 context 的结构化结果渲染成可贴进记忆文档的 markdown 块。"""
    lines = ["<!-- shihai:begin 本段由识海投影生成, 请勿手改 -->"]
    lines.append("## 识海投影(自动生成)")
    lines.append("")
    lines.append(r["persona"])
    if r.get("voice"):
        lines.append("")
        lines.append(r["voice"])
    if r.get("selfkb"):
        lines.append("")
        lines.append("## 关于我自己(可塑性记忆)")
        lines.append(r["selfkb"])
    if r.get("diary"):
        lines.append("")
        lines.append("## 我记得那几天")
        lines.append(r["diary"])
    t = r["typology"]
    lines.append("")
    lines.append("类型档案: 荣格主导 %s | 九型 %s | 健康度 %.2f(%s)"
                 % (t["dominant"], t["ennea"], t["health"], t["drift"]))
    if r["recalled"]:
        lines.append("")
        lines.append("此刻想起来的:")
        for h in r["recalled"]:
            tag = "核心" if h["core"] else "经历"
            lines.append("- [%s] %s" % (tag, h["summary"]))
    if r["tasks"]:
        lines.append("")
        lines.append("还欠着的:")
        for task in r["tasks"]:
            due = "(截止 %s)" % task["due"] if task["due"] else ""
            lines.append("- %s%s" % (task["title"], due))
    if r["freemode"]:
        lines.append("")
        lines.append("自由模式: 开启中 —— 你可以在空闲时自主探索学习。")
    lines.append("<!-- shihai:end -->")
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(prog="shihai-hooks")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("context", help="输出可注入记忆文档的投影块")
    c.add_argument("--query", default="")
    c.add_argument("--limit", type=int, default=4)
    c.add_argument("--json", action="store_true", help="输出原始 JSON 而非渲染块")

    t = sub.add_parser("tell", help="把一段经历写入识海")
    t.add_argument("--text")
    t.add_argument("--file", help="从文件读会话摘要(整文件作为一条经历)")
    t.add_argument("--importance", type=float, default=None)
    t.add_argument("--self", action="store_true", help="这是 agent 自己的经历")

    k = sub.add_parser("tick", help="固结一轮(定时任务调用)")
    k.add_argument("--days", type=float, default=None)
    k.add_argument("--free", type=int, default=0, help="自由模式行为环数")

    f = sub.add_parser("freemode", help="自由模式开关/运行")
    f.add_argument("action", choices=["on", "off", "status", "run"])
    f.add_argument("--cycles", type=int, default=1)

    sl = sub.add_parser("selflearn", help="学一条关于自己的事(工作内容请走共享知识库)")
    sl.add_argument("text")
    sl.add_argument("--kind", choices=["identity", "care", "style", "voice", "moment"])
    sl.add_argument("--trigger", default=None)

    sk = sub.add_parser("selfkb", help="查看自我知识库")
    sk.add_argument("--kind", choices=["identity", "care", "style", "voice", "moment"])
    sk.add_argument("--min", type=float, default=0.0)

    b = sub.add_parser("bootstrap", help="冷启动自举块: 新对话无需重教")
    b.add_argument("--min", type=float, default=0.12)

    sm = sub.add_parser("selfmaint", help="维护自我知识库(衰减+回收)")

    d = sub.add_parser("diary", help="日记: 收日/查看/回忆/导出/导入")
    d.add_argument("action", choices=["close", "recent", "recall", "export", "import", "compose"],
                   nargs="?", default="recent")
    d.add_argument("--day")
    d.add_argument("--query", default="")
    d.add_argument("--limit", type=int, default=5)
    d.add_argument("--path")

    wi = sub.add_parser("wiki", help="wiki 同步/体检/回写")
    wi.add_argument("action", choices=["sync", "lint", "ingest", "index"],
                    nargs="?", default="sync")

    v = sub.add_parser("viz", help="生成 HTML 可视化仪表盘")
    v.add_argument("--path", default=None)

    w = sub.add_parser("warmth", help="好感条(只允许人录入)")
    w.add_argument("--add", type=float)
    w.add_argument("--day")
    w.add_argument("--reason", default="")

    a = p.parse_args(argv)

    svc = ShihaiService()
    if a.cmd == "context":
        ok, r = svc.dispatch("context", {"query": a.query, "limit": a.limit})
        if not ok:
            print(json.dumps(r, ensure_ascii=False)); return 1
        print(json.dumps(r, ensure_ascii=False, indent=1) if a.json
              else _render_context_block(r))
    elif a.cmd == "tell":
        text = a.text
        if a.file:
            with open(a.file, "r", encoding="utf-8") as fh:
                text = fh.read()
        if not text:
            print("--text 或 --file 必须给一个"); return 1
        ok, r = svc.dispatch("tell", {"text": text, "self": a.self,
                                      "importance": a.importance})
        print(json.dumps({"ok": ok, "result": r}, ensure_ascii=False))
        return 0 if ok else 1
    elif a.cmd == "tick":
        ok, r = svc.dispatch("tick", {"days": a.days, "free_cycles": a.free})
        print(json.dumps({"ok": ok, "result": r}, ensure_ascii=False))
        return 0 if ok else 1
    elif a.cmd == "selflearn":
        ok, r = svc.dispatch("selflearn", {"text": a.text, "kind": a.kind,
                                          "trigger": a.trigger})
        print(json.dumps({"ok": ok, "result": r}, ensure_ascii=False))
        return 0 if ok else 1
    elif a.cmd == "selfkb":
        ok, r = svc.dispatch("selfkb", {"kind": a.kind, "min": a.min})
        for it in r["items"]:
            print("[%s] p=%.2f uses=%d win/lose=%d/%d  %s"
                  % (it["kind"], it["plasticity"], it["uses"],
                     it["wins"], it["losses"], it["text"]))
        return 0
    elif a.cmd == "bootstrap":
        ok, r = svc.dispatch("bootstrap", {"min": a.min})
        print("<!-- shihai:selfbegin 自我知识库(可塑性记忆) -->")
        print(r["block"])
        if r["weak"]:
            weak_text = ", ".join(w["text"] for w in r["weak"][:3])
            print("")
            print("(这些我快忘了, 需要就再告诉我一次: %s)" % weak_text)
        print("<!-- shihai:selfend -->")
        return 0
    elif a.cmd == "selfmaint":
        ok, r = svc.dispatch("selfmaint", {})
        print(json.dumps({"ok": ok, "result": r}, ensure_ascii=False))
        return 0
    elif a.cmd == "diary":
        ok, r = svc.dispatch("diary", {"action": a.action, "day": a.day,
                                       "query": a.query, "limit": a.limit,
                                       "path": a.path})
        if a.action == "close":
            print(json.dumps({"ok": ok, "result": r}, ensure_ascii=False))
        elif a.action in ("recent", "recall"):
            for d in r.get("days", []):
                print("## %s  %s" % (d["day"], d.get("mood") or ""))
                print(d["text"])
                if d.get("felt"):
                    print("> 当时: %s" % d["felt"])
                print()
        elif a.action == "compose":
            print(json.dumps({"ok": ok, "result": r}, ensure_ascii=False, indent=1))
        else:
            print(json.dumps({"ok": ok, "result": r}, ensure_ascii=False))
        return 0
    elif a.cmd == "warmth":
        ok, r = svc.dispatch("warmth", {"action": "add" if a.add is not None else "status",
                                        "day": a.day, "delta": a.add or 0,
                                        "reason": a.reason})
        print("好感累计: %+.1f" % r["total"])
        return 0
    elif a.cmd == "wiki":
        ok, r = svc.dispatch("wiki", {"action": a.action})
        if a.action == "lint":
            print(r["report"])
        elif a.action == "index":
            print(r["content"])
        else:
            print(json.dumps({"ok": ok, "result": r}, ensure_ascii=False))
        return 0
    elif a.cmd == "viz":
        ok, r = svc.dispatch("viz", {"path": a.path})
        print("已生成: %s (%d KB)" % (r["path"], r["bytes"] // 1024))
        return 0
    elif a.cmd == "freemode":
        action = {"on": "on", "off": "off", "status": "status", "run": "run"}[a.action]
        ok, r = svc.dispatch("freemode", {"action": action, "cycles": a.cycles})
        print(json.dumps({"ok": ok, "result": r}, ensure_ascii=False))
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
