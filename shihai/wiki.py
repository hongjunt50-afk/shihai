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

    # -- ingest: 反向闭环(改 md → 回写库) --------------------------------
    def ingest_edits(self):
        """扫描 wiki/ 下被人改过的页面, 把改动写回 SQLite。

        这是 sync 的反向: sync 是从库往外投影, ingest 是把人在 Markdown 里的
        修订收回库。两边的文件 mtime 比库里的 updated 新, 就认为是人改的。

        三类页面各有回写方式:
            wiki/self/*.md   → self_knowledge(整页替换该 kind)
            wiki/days/*.md   → diary(按日期, 标 edited=1 保护)
            wiki/topics/*.md → 只读提示(主题页是派生页, 不反向写)
        """
        self.ensure()
        stats = {"self_pages": 0, "days": 0, "skipped": []}
        wikidir = os.path.join(self.root, "wiki")

        # 自我知识页: 整页成批回写(页面是"某类自我知识"的全部内容)
        selfdir = os.path.join(wikidir, "self")
        from .kb import KINDS
        for fn in os.listdir(selfdir) if os.path.isdir(selfdir) else []:
            if not fn.endswith(".md"):
                continue
            kind = fn[:-3]
            if kind not in KINDS:
                stats["skipped"].append(fn)
                continue
            path = os.path.join(selfdir, fn)
            items = _parse_bullets(open(path, encoding="utf-8").read())
            if not items:
                continue
            existing = {r["text"] for r in self.store.self_knowledge(kind=kind)}
            added = 0
            for text in items:
                if text in existing:
                    continue
                # 人在 wiki 里写的条目, 置信度高(人亲自确认过)
                self.store.learn_self(kind, text, source="human-wiki", init=0.7)
                added += 1
            if added:
                stats["self_pages"] += 1

        # 日记页: 按日期回写正文, 标记 edited=1(机器此后不再覆盖)
        daydir = os.path.join(wikidir, "days")
        for fn in os.listdir(daydir) if os.path.isdir(daydir) else []:
            if not fn.endswith(".md"):
                continue
            day = fn[:-3]
            path = os.path.join(daydir, fn)
            raw = open(path, encoding="utf-8").read()
            body = _strip_meta(raw)
            if not body:
                continue
            row = self.store.diary_of(day)
            if row is None:
                self.store.add_diary(day, body, mood="平静")
                stats["days"] += 1
            elif body.strip() != (row["text"] or "").strip():
                self.store.edit_diary(day, text=body.strip())
                stats["days"] += 1

        self._log("ingest", "%d 自我页 / %d 日记页" % (stats["self_pages"], stats["days"]))
        return stats

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


def _parse_bullets(text):
    """从 markdown 里抽 `- 内容` 行, 去掉机器加的 (_稳固度 ..._) 后缀。"""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith(("- ", "* ")):
            continue
        body = line[2:].strip()
        body = re.sub(r"\s*_\(.*?\)_\s*$", "", body)   # 去掉机器元信息
        if body and len(body) > 2:
            out.append(body)
    return out


def _strip_meta(text):
    """去掉标题行、`>` 引用行(机器生成的心智元信息)和 wiki 链接。"""
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("# ") or s.startswith(">") or s.startswith("[[") or not s:
            continue
        lines.append(line)
    return chr(10).join(lines).strip()


def _slug(s):
    out = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in s)
    return re.sub(r"-+", "-", out).strip("-")[:40] or "topic"
