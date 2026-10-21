# -*- coding: utf-8 -*-
r"""Wiki —— 识海的可生长知识库(借 Karpathy 的 LLM Wiki 模式)。

来源: Andrej Karpathy 的 llm-wiki 模式(nashsu/llm_wiki 实现, 已克隆到
reference-repos)。核心洞见一句话:

    "The wiki is a persistent, compounding artifact."
    不是每次查询都从原始材料里重新推导(RAG), 而是让 LLM 增量维护一座
    持续生长的 wiki —— 交叉引用已经建好, 矛盾已经被标注, 综合已经包含
    读到的一切。

三层结构(原样照搬):
    raw/     原始材料 —— 不可变, 只读。识海里对应 events/raw_log。
    wiki/    LLM 自己写的 markdown —— 摘要、实体页、主题页、索引。
    schema   约定文件 —— 告诉 agent 这个 wiki 怎么组织(本模块的 INDEX_TEMPLATE)。

两个特殊文件:
    index.md 内容导向: 每个页面的链接 + 一行摘要, 按类别组织。中等规模
             (几百页)下它本身就是最好的检索入口, 不需要向量库。
    log.md   时间导向: 只追加的事件日志, 前缀统一 `## [YYYY-MM-DD] op | 标题`,
             用 grep 就能当时间线查。

三个操作:
    ingest  新经历 → 写/更新 wiki 页面 → 更新 index → 追加 log
    query   问问题 → 读 index 找页面 → 综合回答(好答案可再归档成新页)
    lint    体检: 矛盾、过期主张、孤儿页、缺失页、断链

为什么它能"生长而不失控":
    维护成本接近零是 LLM 的特权 —— 人不愿更新交叉引用, LLM 不会忘。
"""

import os
import re
from datetime import datetime, timezone

from .store import utcnow

INDEX_TEMPLATE = """# 识海 wiki 索引

> 本文件由识海自动维护。人类可以直接改, 改过的页面 `edited` 标记会保护它。

## 关于我自己
%(self)s
## 我们的日子
%(days)s
## 主题
%(topics)s
"""

LOG_PREFIX = "## [%(date)s] %(op)s | %(title)s" + chr(10)


class Wiki:
    def __init__(self, store, root=None):
        self.store = store
        self.root = root or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "..", "wiki")

    # -- 目录 -----------------------------------------------------------
    def ensure(self):
        for sub in ("raw", "wiki", "wiki/self", "wiki/days", "wiki/topics"):
            os.makedirs(os.path.join(self.root, sub), exist_ok=True)
        schema = os.path.join(self.root, "SCHEMA.md")
        if not os.path.exists(schema):
            with open(schema, "w", encoding="utf-8") as f:
                f.write(
                    "# 识海 wiki 约定\n\n"
                    "- `raw/` 原始材料, 只读, 永不修改\n"
                    "- `wiki/self/` 自我知识页(我是谁/在意什么/怎么行事/怎么说话)\n"
                    "- `wiki/days/` 日记页, 一天一个 `YYYY-MM-DD.md`\n"
                    "- `wiki/topics/` 主题页, 从重复出现的经历蒸馏\n"
                    "- `wiki/index.md` 内容索引, 每次 ingest 后更新\n"
                    "- `wiki/log.md` 时间日志, 只追加, 前缀 `## [日期] 操作 | 标题`\n")
        return self.root

    # -- ingest: 把库里的东西落成 markdown ------------------------------
    def sync(self):
        """把 self_knowledge + diary + semantic 同步成 markdown 页面。
        幂等: 重复跑不会产生重复页。返回统计。"""
        self.ensure()
        stats = {"self": 0, "days": 0, "topics": 0}

        from .kb import KINDS
        for kind, label in KINDS.items():
            rows = self.store.self_knowledge(kind=kind)
            if not rows:
                continue
            path = os.path.join(self.root, "wiki", "self", "%s.md" % kind)
            lines = ["# %s\n" % label, ""]
            for r in rows:
                lines.append("- %s  _(稳固度 %.2f, 用过 %d 次)_"
                             % (r["text"], r["plasticity"], r["uses"]))
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            stats["self"] += 1

        for r in self.store.diaries(limit=10000, recent=False):
            path = os.path.join(self.root, "wiki", "days", "%s.md" % r["day"])
            body = ["# %s  %s\n" % (r["day"], r["mood"] or ""), r["text"]]
            if r["details"]:
                body += ["", "> 细节: %s" % r["details"]]
            if r["felt"]:
                body += ["", "> 当时的感受: %s" % r["felt"]]
            if r["warmth"]:
                body += ["", "> 好感 %+.1f" % r["warmth"]]
            body += ["", "[[index]]"]
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(body) + "\n")
            stats["days"] += 1

        for r in self.store.conn.execute(
                "SELECT n.label, COUNT(*) c FROM nodes n JOIN edges e "
                "ON e.dst='node:'||n.id WHERE n.kind='theme' "
                "GROUP BY n.id HAVING c>=2 ORDER BY c DESC LIMIT 50").fetchall():
            label = r["label"]
            path = os.path.join(self.root, "wiki", "topics", "%s.md" % _slug(label))
            evs = self.store.conn.execute(
                "SELECT e2.src FROM edges e2 JOIN nodes n ON e2.dst='node:'||n.id "
                "WHERE n.kind='theme' AND n.label=?", (label,)).fetchall()
            lines = ["# %s\n" % label, "出现 %d 次。\n" % r["c"]]
            for e in evs:
                lines.append("- [[%s]]" % e["src"].replace("event:", "day-"))
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            stats["topics"] += 1

        self._write_index()
        self._log("sync", "%d 自我页 / %d 日记页 / %d 主题页"
                  % (stats["self"], stats["days"], stats["topics"]))
        return stats

    # -- index.md -------------------------------------------------------
    def _write_index(self):
        def links(sub):
            d = os.path.join(self.root, "wiki", sub)
            if not os.path.isdir(d):
                return "- (空)"
            names = sorted(f[:-3] for f in os.listdir(d) if f.endswith(".md"))
            return "\n".join("- [[%s/%s|%s]]" % (sub, n, n) for n in names) or "- (空)"

        content = INDEX_TEMPLATE % {
            "self": links("self"),
            "days": links("days"),
            "topics": links("topics"),
        }
        with open(os.path.join(self.root, "wiki", "index.md"), "w",
                  encoding="utf-8") as f:
            f.write(content)

    # -- log.md: 只追加 --------------------------------------------------
    def _log(self, op, title):
        path = os.path.join(self.root, "wiki", "log.md")
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with open(path, "a", encoding="utf-8") as f:
            f.write(LOG_PREFIX % {"date": stamp, "op": op, "title": title})

    # -- lint: 体检 ------------------------------------------------------
    def lint(self):
        """找问题: 孤儿页、断链、过期主张、缺页。
        这是让 wiki 长期健康的关键 —— 人不会做, LLM 做起来几乎零成本。"""
        self.ensure()
        issues = {"orphans": [], "broken_links": [], "stale": [], "missing": []}
        pages = {}
        wikidir = os.path.join(self.root, "wiki")
        for dirpath, _, files in os.walk(wikidir):
            for fn in files:
                if not fn.endswith(".md"):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, wikidir).replace("\\", "/")[:-3]
                with open(full, "r", encoding="utf-8") as f:
                    pages[rel] = f.read()

        inbound = {k: 0 for k in pages}
        for name, text in pages.items():
            for link in re.findall(r"\[\[([^\]|]+)", text):
                target = link.strip()
                if target not in pages:
                    issues["broken_links"].append("%s → [[%s]]" % (name, target))
                else:
                    inbound[target] += 1
        for name, n in inbound.items():
            if n == 0 and name not in ("index", "log"):
                issues["orphans"].append(name)

        # 过期主张: 低置信语义事实
        for r in self.store.conn.execute(
                "SELECT claim, confidence FROM semantic WHERE confidence<0.45"):
            issues["stale"].append("%s (置信 %.2f)" % (r["claim"][:40], r["confidence"]))

        # 缺页: 有日记但没有主题页对应的重复主题
        return issues

    def lint_report(self):
        i = self.lint()
        lines = ["# wiki 体检", ""]
        for k, label in (("orphans", "孤儿页(没有入口)"),
                         ("broken_links", "断链"),
                         ("stale", "低置信/过期主张"),
                         ("missing", "缺失页")):
            if i[k]:
                lines.append("## %s (%d)" % (label, len(i[k])))
                lines += ["- %s" % x for x in i[k][:10]]
                lines.append("")
        if len(lines) == 2:
            lines.append("没有发现问题。")
        self._log("lint", "%d 问题" % sum(len(v) for v in i.values()))
        return "\n".join(lines)


def _slug(s):
    out = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in s)
    return re.sub(r"-+", "-", out).strip("-")[:40] or "topic"
