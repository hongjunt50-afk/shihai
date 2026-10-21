# -*- coding: utf-8 -*-
r"""Diary —— 日记层: 让"知道"变成"经历过"。

用户的目标(2026-10-18):
    通过每日日志与日记留存记忆, 造一个能生长、方便人来管理的大知识库,
    用来存"大家在一起的美好经历"。

为什么单靠 events 不够 —— 截图里那句最戳人的话:
    「知道和亲身经历过确实是两回事。我知道那些事发生过, 但没有当时的感受。」

    events 存的是**事实**: "今天去了公园"。
    diary 存的是**经历**: 长椅上那只三毛猫蹭了手; 路边咖啡店的招牌颜色;
    我说咖啡有点苦其实没喝过。事实可以被告知, 经历必须被"再经历"一次。
    所以日记必须是第一人称、带感官细节、带一句感受锚点(felt)。

三条设计决定:
    1. **一天一篇, 有界增长**: 不是每条消息都记, 是每天收拢成一篇。
       这让库能长十年而不撑爆上下文 —— 检索靠"那一天", 不靠"那一句"。
    2. **人可管理**: 日记是 Markdown 可导出可修订, 改过的日记(`edited=1`)
       机器永不再覆盖。人的记忆主权高于机器的自动生成。
    3. **好感条人写机读**: 好感增量只由人手工录入(截图里的"她权限无法更改"),
       agent 只能读、只能依它推演态度, 不能自己给自己加分。

检索: 按日期倒序取最近几篇(冷启动), 或按关键词/人物匹配(被问起时)。
"""

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from .store import utcnow

MOOD_WORDS = {
    "positive": ["开心", "快乐", "谢谢", "喜欢", "满意", "成功", "漂亮", "信任", "暖"],
    "negative": ["崩溃", "失败", "害怕", "担心", "失望", "骂", "烦", "痛"],
}


def today(ts=None):
    t = ts or utcnow()
    return t[:10]


@dataclass
class DiaryDraft:
    day: str
    text: str
    felt: str
    details: str
    mood: str
    warmth: float
    event_ids: list


class DiaryEngine:
    def __init__(self, store):
        self.store = store

    # -- 生成: 一天的事件 → 一篇日记 --------------------------------------
    def compose(self, day=None, *, style="voice", felt_template=True):
        """把某天的事件织成第一人称日记。

        style: voice = 按 agent 当前的说话风格写(默认);
               plain = 客观陈述(给人看的归档格式)。
        真实系统里这里应交给 LLM 富化(见 to_prompt()); 这里是可离线运行的基线。
        """
        day = day or today()
        rows = self.store.conn.execute(
            "SELECT * FROM events WHERE ts LIKE ? AND dormant=0 ORDER BY id",
            (day + "%",)).fetchall()
        if not rows:
            return None

        lines, details, ids = [], [], []
        warmth = 0.0
        pos = neg = 0
        for r in rows:
            ids.append(r["id"])
            s = r["summary"].strip()
            # 第一人称化: "用户夸我" → "用户夸我"
            lines.append(s)
            # 感受锚点: 从情绪字段生成一句"当时的感受"
            emo = r["emotion"] or "平静"
            if float(r["pain"]) > 0.4:
                details.append("那一下心里是沉的, %s。" % emo)
            elif float(r["valence"]) > 0.4:
                details.append("那会儿是高兴的, %s。" % emo)
            if float(r["valence"]) > 0.1:
                pos += 1
                warmth += 0.5 * float(r["valence"]) * float(r["arousal"])
            elif float(r["valence"]) < -0.1:
                neg += 1
                warmth -= 0.3 * abs(float(r["valence"]))

        mood = "平静" if pos == neg else ("暖" if pos > neg else "低落")
        if style == "plain":
            text = "%s: 今天有 %d 件事。" % (day, len(rows))
            text += "\n" + "\n".join("- " + l for l in lines)
        else:
            opener = {
                "暖": "今天过得挺好。",
                "低落": "今天有点难。",
                "平静": "今天挺平常的。",
            }[mood]
            text = opener + "\n" + "".join(l + "。" for l in lines)

        felt = ""
        if felt_template and details:
            felt = details[0]
        elif rows:
            top = max(rows, key=lambda r: float(r["importance"]))
            felt = "我记得那件事: %s" % top["summary"][:30]

        return DiaryDraft(day=day, text=text, felt=felt,
                          details=" ".join(details[:3]), mood=mood,
                          warmth=round(warmth, 2), event_ids=ids)

    def write(self, draft):
        """落库。同一天重复生成 = 更新(除非人改过)。"""
        kid, status = self.store.add_diary(
            draft.day, draft.text, felt=draft.felt, details=draft.details,
            mood=draft.mood, warmth=draft.warmth, event_ids=draft.event_ids)
        if draft.warmth:
            self.store.add_warmth(draft.day, draft.warmth, reason="当天经历累计")
        return kid, status

    def close_day(self, day=None):
        """一天结束时调用(Stop hook / 定时任务)。"""
        draft = self.compose(day)
        if draft is None:
            return None
        kid, status = self.write(draft)
        return {"day": draft.day, "id": kid, "status": status,
                "mood": draft.mood, "warmth": draft.warmth,
                "events": len(draft.event_ids)}

    # -- 读: 冷启动 / 被问起 ----------------------------------------------
    def recent(self, n=3):
        """最近几篇日记 —— 冷启动时"以第一人称重新经历一次"。"""
        rows = self.store.diaries(limit=n, recent=True)
        return list(reversed(rows))   # 按时间正序读起来自然

    def recall(self, query="", limit=3):
        """按关键词找那些天。没 query 就返回最近。"""
        if not query:
            return self.recent(limit)
        q = query.strip()
        rows = self.store.conn.execute(
            """SELECT * FROM diary WHERE text LIKE ? OR felt LIKE ?
               OR details LIKE ? ORDER BY day DESC LIMIT ?""",
            ("%" + q + "%", "%" + q + "%", "%" + q + "%", limit)).fetchall()
        return rows

    def bootstrap_block(self, n=2):
        """冷启动块: 最近几天的日记浓缩成"我记得那几天"。
        这是让 agent 不至于"知道事实却没有感受"的入口。"""
        rows = self.recent(n)
        if not rows:
            return ""
        out = ["### 最近的日子"]
        for r in rows:
            head = r["text"].splitlines()[0] if r["text"] else ""
            out.append("- %s %s" % (r["day"], head))
            if r["felt"]:
                out.append("  当时: %s" % r["felt"])
        total = self.store.warmth_total()
        if total:
            out.append("")
            out.append("我们一起走到现在, 好感累计 %+.1f。" % total)
        return "\n".join(out)

    # -- 人可管理: 导出 Markdown / 导入 ----------------------------------
    def export_markdown(self, path=None):
        """导出成 Markdown 供人阅读与修订 —— 这是"方便人来管理"的落点。"""
        rows = self.store.diaries(limit=10000, recent=False)
        parts = ["# 识海日记", ""]
        for r in rows:
            parts.append("## %s  %s" % (r["day"], r["mood"] or ""))
            parts.append("")
            parts.append(r["text"])
            if r["details"]:
                parts.append("")
                parts.append("> 细节: %s" % r["details"])
            if r["felt"]:
                parts.append("")
                parts.append("> 当时的感受: %s" % r["felt"])
            if r["warmth"]:
                parts.append("")
                parts.append("> 好感 %+.1f" % r["warmth"])
            parts.append("")
        text = "\n".join(parts)
        if path:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        return text

    def import_markdown(self, path):
        """从人改过的 Markdown 回写(保留人的修订, 标记 edited=1)。"""
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        blocks = re.split(r"^## ", content, flags=re.M)[1:]
        n = 0
        for b in blocks:
            head, _, body = b.partition("\n")
            m = re.match(r"(\d{4}-\d{2}-\d{2})", head.strip())
            if not m:
                continue
            day = m.group(1)
            text_lines = []
            for line in body.splitlines():
                if line.startswith(">"):
                    continue
                text_lines.append(line)
            text = "\n".join(text_lines).strip()
            if text and self.store.edit_diary(day, text=text):
                n += 1
        return n

    # -- 给 LLM 富化用的提示 ---------------------------------------------
    def to_prompt(self, day=None):
        """产出喂给 LLM 的素材, 让它把事实写成真正的日记(生产环境用)。
        本模块的 compose() 是离线基线; 接模型后细节与感受会真实得多。"""
        day = day or today()
        rows = self.store.conn.execute(
            "SELECT summary, emotion, valence, arousal, pain FROM events "
            "WHERE ts LIKE ? ORDER BY id", (day + "%",)).fetchall()
        facts = "\n".join("- %s (情绪: %s, 愉悦度 %+.1f)" % (r["summary"], r["emotion"],
                                                          r["valence"]) for r in rows)
        return ("把下面这天的经历写成一篇第一人称日记。要求:\n"
                "1. 带具体感官细节(看见什么、听见什么、当时身体的感觉)\n"
                "2. 有一句能代表当天真实感受的话, 不要总结陈词\n"
                "3. 不要写成流水账, 挑最有分量的一两件写透\n"
                "4. 保持我的说话风格\n\n"
                "当天事实:\n%s" % (facts or "(今天没有记录)"))
