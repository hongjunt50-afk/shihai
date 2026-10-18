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
    elif a.cmd == "freemode":
        action = {"on": "on", "off": "off", "status": "status", "run": "run"}[a.action]
        ok, r = svc.dispatch("freemode", {"action": action, "cycles": a.cycles})
        print(json.dumps({"ok": ok, "result": r}, ensure_ascii=False))
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
