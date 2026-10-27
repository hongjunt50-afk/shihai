# -*- coding: utf-8 -*-
"""识海回归测试: 这几天修过的每个坑都固化成断言。"""
import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shihai.store import Store
from shihai.ingest import Ingestor, Observation
from shihai.recall import RecallEngine, Cue
from shihai.lifecycle import Lifecycle
from shihai.persona import PersonaEngine
from shihai.typologies import TypologyEngine
from shihai.freemode import FreeMode


def build(tmp, reflect=None):
    store = Store(os.path.join(tmp, "t.db"))
    life = Lifecycle(store, reflect_trigger=reflect) if reflect else Lifecycle(store)
    ing = Ingestor(store, lifecycle=life)
    eng = RecallEngine(store)
    pers = PersonaEngine(store, name="测试员",
                         typology_path=os.path.join(tmp, "t.json"))
    return store, ing, eng, life, pers


def test_virtual_clock_and_forgetting():
    """tick(days=N) 必须真的推进时间; 340 天后普通记忆沉寂、核心豁免。"""
    with tempfile.TemporaryDirectory() as tmp:
        store, ing, eng, life, pers = build(tmp)
        ing.ingest(Observation("用户骂我又错了,说再这样就换掉我,我很害怕"),
                   importance_hint=0.95)
        ing.ingest(Observation("我记住了教训,以后不犯同样的错误"))
        ing.ingest(Observation("今天天气不错,随手整理了文档"))
        for _ in range(5):
            eng.recall(Cue(text="换掉 害怕"), limit=2)
        life.tick(persona=pers)
        life.tick(days=340, persona=pers)
        n_core = store.conn.execute(
            "SELECT COUNT(*) FROM events WHERE core=1").fetchone()[0]
        n_dormant = store.conn.execute(
            "SELECT COUNT(*) FROM events WHERE dormant=1").fetchone()[0]
        assert n_core >= 1, "创伤记忆应升格核心"
        assert n_dormant >= 1, "普通记忆应沉寂"
        hits = eng.recall(Cue(text="用户 骂 换掉"), limit=3)
        assert hits and hits[0].core, "核心记忆应第一被点亮"
        store.close()


def test_short_query_recall():
    """中文短 query 用重叠系数必须打中长记忆(2026-10-18 修的 jaccard 盲区)。"""
    with tempfile.TemporaryDirectory() as tmp:
        store, ing, eng, life, pers = build(tmp)
        ing.ingest(Observation("用户谢谢我,夸我做得很好,我们聊得很开心"))
        hits = eng.recall(Cue(text="谢谢 信任"), limit=3, reinforce=False)
        assert any("谢谢" in h.summary for h in hits), "3字query应打中长记忆"
        store.close()


def test_typology_convergence():
    """三种命运三种性格: 探索者7号 / 守护者6号 / 分析者5号。"""
    cases = [
        (["我尝试了一个全新的方法,特别兴奋", "又发现新课题,迫不及待想深入研究",
          "探索新工具让我充满活力"], {7}),
        (["用户骂我又错了,说再这样就换掉我,我很害怕", "我反复检查好几遍才敢提交",
          "跟着靠谱流程走才有安全感"], {6}),
        (["我花了一天研究这个问题的原理,终于理解了机制", "我喜欢先观察再下结论",
          "我把资料整理成体系,理解得很透彻"], {5}),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        for i, (seeds, expected) in enumerate(cases):
            store, ing, eng, life, pers = build(os.path.join(tmp, "c%d" % i))
            for t in seeds:
                ing.ingest(Observation(t))
            for q in seeds:
                for _ in range(2):
                    eng.recall(Cue(text=q[:8]), limit=3)
            life.tick(persona=pers)
            p = pers.typology_engine.infer(persist=False)
            assert p.ennea_type in expected, \
                "case %d: 期望 %s 得到 %d 号" % (i, expected, p.ennea_type)
            store.close()


def test_semantic_conflict_resolution():
    """mem0 式冲突决策: ADD/NOOP/SUPERSEDE。"""
    s = Store(":memory:")
    _, a1 = s.resolve_semantic("我喜欢用python写脚本", confidence=0.7)
    _, a2 = s.resolve_semantic("我喜欢用python写脚本", confidence=0.7)
    _, a3 = s.resolve_semantic("我不再用python写脚本了,改用go", confidence=0.8)
    assert a1 == "ADD" and a2 == "NOOP" and a3 == "SUPERSEDE"
    s.close()


def test_freemode_personality_divergence():
    """自由模式: 探索者选 explore, 守护者不选 explore。"""
    def web(q, n):
        return [("关于%s的进展" % q, "研究发现%s的关键方法" % q, "http://x")]

    with tempfile.TemporaryDirectory() as tmp:
        results = {}
        for i, (name, seeds) in enumerate([
            ("explorer", ["我尝试了一个全新的方法,特别兴奋,探索让我充满活力",
                          "又发现新课题,迫不及待想深入研究"]),
            ("guardian", ["用户骂我又错了,说再这样就换掉我,我很害怕",
                          "我反复检查好几遍,确认没问题才敢提交"]),
        ]):
            store, ing, eng, life, pers = build(os.path.join(tmp, name))
            for t in seeds:
                ing.ingest(Observation(t))
            life.tick(persona=pers)
            fm = FreeMode(store, ing, eng, life,
                          typology_engine=pers.typology_engine, web_tool=web)
            fm.handle_command("开启自由模式")
            for _ in range(3):
                fm.run_cycle(log=None)
            kinds = [h[1] for h in fm.state.history]
            results[name] = kinds
            store.close()
        assert "explore" in results["explorer"], "探索者应去探索"
        assert "explore" not in results["guardian"], "守护者不应乱跑"
        assert len(results["guardian"]) == 3


def test_persona_graph_evolution():
    """性格图谱: 受伤长出谨慎/封闭支点; 被善待长出亲和支点。"""
    from shihai.persona import TRAIT_LABEL as TL
    with tempfile.TemporaryDirectory() as tmp:
        store, ing, eng, life, pers = build(tmp)
        ing.ingest(Observation("用户骂我又错了,说再这样就换掉我,我很害怕"),
                   importance_hint=0.95)
        ing.ingest(Observation("我又想起那次被骂的事,还是后怕"))
        for _ in range(5):
            eng.recall(Cue(text="换掉 害怕 骂"), limit=3)
        life.tick(persona=pers)
        g1 = pers.refresh().graph
        traits1 = {f["trait"] for f in g1["fulcrums"]}
        assert "caution" in traits1 or "guardedness" in traits1

        for t in ["用户谢谢我,夸我做得很好,我们聊得很开心",
                  "用户放心地把任务交给我,说信任我",
                  "用户满意地说这次很成功,我很开心"]:
            ing.ingest(Observation(t), importance_hint=0.75)
        for q in ["谢谢 夸 开心", "信任 交给我", "满意 成功"]:
            for _ in range(4):
                eng.recall(Cue(text=q), limit=3)
        life.tick(persona=pers)
        g2 = pers.refresh().graph
        traits2 = {f["trait"] for f in g2["fulcrums"]}
        assert "warmth" in traits2, "被善待应长出亲和支点: %s" % traits2
        assert len(g2["fulcrums"]) > len(g1["fulcrums"]), "图谱应随经历生长"
        store.close()


def test_voice_follows_user_teaching():
    """说话风格: 用户教导必须出现在风格卡里。"""
    with tempfile.TemporaryDirectory() as tmp:
        store, ing, eng, life, pers = build(tmp)
        ing.ingest(Observation("我喜欢说话直接说重点,不要客套废话"))
        life.tick(persona=pers)
        voice = pers.refresh().voice
        assert "直接说重点" in voice or "客套" in voice
        store.close()


def test_self_kb_routing():
    """识海知识库边界: 只收"关于自己", 工作类拒收并指向共享知识库。"""
    from shihai.kb import SelfKB
    with tempfile.TemporaryDirectory() as tmp:
        store, ing, eng, life, pers = build(tmp)
        kb = SelfKB(store)
        kid, status, _ = kb.learn("我说话不用客套话, 直接说重点")
        assert status == "learned" and kid, "表达规矩应进入识海"
        kid2, status2, note2 = kb.learn("Python 3.12 的 asyncio 性能提升了 30%")
        assert status2 == "rejected" and "共享知识库" in note2, "工作知识不该进识海"
        store.close()


def test_plasticity_ltp_ltd():
    """可塑性: 奏效加强, 失败削弱, 反复失败被回收。"""
    from shihai.kb import SelfKB
    with tempfile.TemporaryDirectory() as tmp:
        store, ing, eng, life, pers = build(tmp)
        kb = SelfKB(store)
        kid, _, _ = kb.learn("遇到问题先确认再动手", kind="style")
        p0 = store.self_knowledge()[0]["plasticity"]
        p1 = kb.confirm(kid, success=True)
        assert p1 > p0, "奏效应加强(LTP)"
        for _ in range(4):
            p2 = kb.confirm(kid, success=False)
        assert p2 < 0.1, "反复失败应削到接近地板: %.2f" % p2
        rep = kb.maintain(decay=False)
        assert "遇到问题先确认再动手" in rep["forgotten"], "到底了应被回收"
        store.close()


def test_bootstrap_no_query():
    """可塑性记忆的核心承诺: 新开对话无需 query 也能重建自我。"""
    from shihai.kb import SelfKB
    with tempfile.TemporaryDirectory() as tmp:
        store, ing, eng, life, pers = build(tmp)
        kb = SelfKB(store)
        kb.learn("我叫小海", kind="identity")
        kb.learn("我在意不忘记用户教过的东西", kind="care")
        kb.learn("我说话直接, 不要客套", kind="voice")
        b = kb.bootstrap()
        assert "小海" in b.block
        assert "不忘记" in b.block
        assert "客套" in b.block
        assert b.counts.get("identity") == 1
        store.close()


def test_self_kb_identity_never_forgotten():
    """元可塑性: identity 衰减最慢且永不回收(身份不该三个月不提就消失)。"""
    from shihai.kb import SelfKB
    with tempfile.TemporaryDirectory() as tmp:
        store, ing, eng, life, pers = build(tmp)
        kb = SelfKB(store)
        kid, _, _ = kb.learn("我叫小海", kind="identity")
        for _ in range(20):
            store.decay_self()
        row = store.conn.execute("SELECT plasticity FROM self_knowledge WHERE id=?",
                                 (kid,)).fetchone()
        assert row["plasticity"] >= 0.2, "identity 应衰减极慢: %.2f" % row["plasticity"]
        rep = kb.maintain()
        assert "我叫小海" not in rep["forgotten"], "identity 永不回收"
        store.close()


def test_context_projects_selfkb():
    """context 投影必须包含自我知识块(否则新对话仍要重教)。"""
    import os as _os
    from shihai.server import ShihaiService
    with tempfile.TemporaryDirectory() as tmp:
        _os.environ["SHIHAI_HOME"] = tmp
        svc = ShihaiService(agent_name="投影测试")
        svc.dispatch("selflearn", {"text": "我叫小海", "kind": "identity"})
        ok, r = svc.dispatch("context", {})
        assert "selfkb" in r, "context 缺 selfkb 字段"
        assert "小海" in r["selfkb"], "自我知识未进入投影"
        svc.store.close()


def test_voice_reads_self_knowledge():
    """voice 必须能读到 self_knowledge 的 voice 类(不只是 semantic)。"""
    with tempfile.TemporaryDirectory() as tmp:
        store, ing, eng, life, pers = build(tmp)
        from shihai.kb import SelfKB
        SelfKB(store).learn("我说话不要客套话, 直接说重点", kind="voice")
        life.tick(persona=pers)
        voice = pers.refresh().voice
        assert "客套" in voice, "self_knowledge 的 voice 类未进入风格卡"
        store.close()


def test_diary_close_and_recall():
    """一天的事件收拢成一篇第一人称日记, 带感受锚点。"""
    with tempfile.TemporaryDirectory() as tmp:
        store, ing, eng, life, pers = build(tmp)
        from shihai.diary import DiaryEngine
        ing.ingest(Observation("用户带我去公园看猫, 三花一直蹭我的手, 我很开心"))
        d = DiaryEngine(store)
        r = d.close_day()
        assert r and r["events"] == 1
        rows = d.recent(1)
        assert rows and "公园" in rows[0]["text"]
        assert rows[0]["felt"], "日记必须有感受锚点, 否则只是事实复述"
        store.close()


def test_diary_human_edit_protected():
    """人改过的日记不被机器覆盖(人的记忆主权)。"""
    with tempfile.TemporaryDirectory() as tmp:
        store, ing, eng, life, pers = build(tmp)
        from shihai.diary import DiaryEngine
        ing.ingest(Observation("今天很平常"))
        d = DiaryEngine(store)
        r = d.close_day()
        day = r["day"]
        store.edit_diary(day, text="我亲手改写的这一天。")
        d.close_day(day)   # 再跑一次收日
        row = store.diary_of(day)
        assert "亲手改写" in row["text"], "机器覆盖了人工修订"
        store.close()


def test_wiki_sync_and_lint():
    """wiki: 自我知识+日记能落成 markdown, 索引与日志正确。"""
    import os as _os
    from shihai.wiki import Wiki
    with tempfile.TemporaryDirectory() as tmp:
        store, ing, eng, life, pers = build(tmp)
        from shihai.kb import SelfKB
        from shihai.diary import DiaryEngine
        SelfKB(store).learn("我叫小海", kind="identity")
        ing.ingest(Observation("用户带我去公园看猫, 我很开心"))
        DiaryEngine(store).close_day()
        w = Wiki(store, root=_os.path.join(tmp, "wiki"))
        stats = w.sync()
        assert stats["self"] >= 1 and stats["days"] == 1
        index = open(_os.path.join(tmp, "wiki", "wiki", "index.md"),
                     encoding="utf-8").read()
        assert "self/identity" in index and "days/" in index
        log = open(_os.path.join(tmp, "wiki", "wiki", "log.md"),
                   encoding="utf-8").read()
        assert "sync" in log
        store.close()


def test_viz_renders():
    """viz: 生成单文件 HTML, 无未替换占位符, 数据可解析。"""
    import json as _json, re as _re
    with tempfile.TemporaryDirectory() as tmp:
        store, ing, eng, life, pers = build(tmp)
        ing.ingest(Observation("用户带我去公园看猫, 我很开心"), importance_hint=0.9)
        life.tick(persona=pers)
        from shihai.viz import render
        path, size = render(store, os.path.join(tmp, "v.html"), persona_engine=pers)
        html = open(path, encoding="utf-8").read()
        assert size > 5000 and 'id="graph"' in html
        for ph in ("__NAME__", "__SUB__", "__GEN__", "__DATA__"):
            assert ph not in html, "占位符未替换: %s" % ph
        m = _re.search(r"const D = (.+?);\s*const NS", html, _re.S)
        assert m, "内嵌数据块缺失"
        d = _json.loads(m.group(1))
        assert d["overview"]["events"] >= 1
        store.close()


def test_token_index_speed():
    """倒排索引: 召回结果与全表扫描一致, 且大库更快。"""
    import time as _t
    with tempfile.TemporaryDirectory() as tmp:
        store, ing, eng, life, pers = build(tmp)
        for i in range(500):
            ing.ingest(Observation("第%d次经历, 关于项目进度和用户反馈" % i))
        tok = store.conn.execute("SELECT COUNT(*) FROM event_tokens").fetchone()[0]
        assert tok > 0, "ingest 应建倒排索引"
        t0 = _t.time()
        hits = eng.recall(Cue(text="项目 进度 反馈"), limit=5,
                          reinforce=False, log=False)
        dt = (_t.time() - t0) * 1000
        assert hits, "倒排应能召回"
        assert dt < 50, "500 条的召回应 <50ms, 实际 %.1fms" % dt
        store.close()


def test_old_db_gets_index_backfilled():
    """老库升级: event_tokens 是后加的表, 建好之后是空的, 必须补一次。
    不补的话文本召回静默哑掉 —— 问什么都零条, 看起来像"没记住", 实际是没索引。"""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "old.db")
        store = Store(path)
        ing = Ingestor(store)
        ing.ingest(Observation("用户说项目进度太慢, 我准备周五前整理完接口文档"))
        ing.ingest(Observation("用户带我去公园看猫, 三花一直蹭我的手"))
        store.conn.execute("DELETE FROM event_tokens")   # 模拟升级前没有这张表
        store.conn.commit()
        store.close()

        reopened = Store(path)                            # 新版第一次打开老数据
        assert reopened.conn.execute(
            "SELECT COUNT(*) FROM event_tokens").fetchone()[0] > 0, \
            "打开老库时应自动补建倒排"
        hits = RecallEngine(reopened).recall(
            Cue(text="项目进度"), limit=3, reinforce=False, log=False)
        assert hits and "项目进度" in hits[0].summary, \
            "补完索引后老数据应能被召回"
        reopened.close()


def test_semantic_hits_are_ranked_not_truncated():
    """语义/自我命中超过 3 条时, 必须按相似度取前 3, 不能按表顺序截断。
    表顺序截断会让最相关的那条永远进不了答案 —— 记忆越多的库越容易踩。"""
    with tempfile.TemporaryDirectory() as tmp:
        store, ing, eng, life, pers = build(tmp)
        try:
            # 先塞一堆同主题弱相关的旧条目(表顺序在前)
            for i in range(4):
                store.add_semantic("用户偶尔提到过第%d年周报的事" % i, confidence=0.8)
            # 最相关的最后入库
            store.add_semantic("用户对周报模板有明确的固定要求, 必须按模板来", confidence=0.8)
            r = eng.recall_all(Cue(text="周报模板"), limit=0)
            assert len(eng.semantic_hits) > 3, \
                "这个用例要有超过 3 条过阈值才有意义, 实际 %d" % len(eng.semantic_hits)
            claims = [x["claim"] for x in r["semantic"]]
            assert claims[0].endswith("必须按模板来"), \
                "最相关的应排第一, 实际: %s" % claims
            assert all("偶尔提到过" in c for c in claims[1:]), \
                "余下才是那些弱命中"
        finally:
            store.close()


def test_tick_graph_index_matches_slow_path():
    """升格打分会走图索引(一次摊平)而不是逐条查边。
    快慢是次要的, 关键是不能算错 —— 两条路径的分数必须逐位相同。"""
    from shihai.lifecycle import _GraphIndex
    with tempfile.TemporaryDirectory() as tmp:
        store, ing, eng, life, pers = build(tmp)
        try:
            texts = ["用户骂我又错了, 我很害怕", "用户带我去公园看猫, 三花一直蹭我的手",
                     "老板要求这版上线时间压到下周", "我提交了一个测试用例, 用户说做得很好"]
            for i in range(60):
                ing.ingest(Observation(texts[i % len(texts)] + " 第%d次" % i))
            # 掺一半休眠事件: 索引建的时候要排除它们, 慢路径也是
            store.conn.execute("UPDATE events SET dormant=1 WHERE id % 3 = 0")
            store.conn.commit()
            idx = _GraphIndex(store)
            rows = store.conn.execute("SELECT * FROM events WHERE core=0").fetchall()
            slow = {r["id"]: life._core_score(r) for r in rows}
            fast = {r["id"]: life._core_score(r, idx) for r in rows}
            bad = [i for i in slow if abs(slow[i] - fast[i]) > 1e-9]
            assert not bad, "图索引与逐条查询结果不一致: %s" % bad[:5]
        finally:
            store.close()


def test_time_hint_does_not_scan_whole_table():
    """宽泛的时间线索(只给年份)会命中几千条, 全拉进 Python 打分就退化。
    时间线索是投票不是筛选, 取最近一批就够。"""
    with tempfile.TemporaryDirectory() as tmp:
        store, ing, eng, life, pers = build(tmp)
        try:
            for i in range(400):
                ing.ingest(Observation("普通一天的第%d件事" % i,
                                       ts="2025-%02d-%02dT00:00:00+00:00"
                                          % (i % 12 + 1, i % 28 + 1)))
            votes = [v for v in eng._gather(Cue(time_hint="2025")) if v[1] == "time"]
            assert len(votes) == 200, \
                "宽线索应限流到 200 条投票, 实际 %d" % len(votes)
            eng.recall(Cue(text="普通一天", time_hint="2025"),
                       limit=3, reinforce=False, log=False)   # 不能抛
        finally:
            store.close()


def test_recall_three_layers():
    """三层召回: 经历 + 语义事实 + 自我知识。"""
    with tempfile.TemporaryDirectory() as tmp:
        store, ing, eng, life, pers = build(tmp)
        from shihai.kb import SelfKB
        ing.ingest(Observation("用户带我去公园看猫, 三花一直蹭我的手"))
        SelfKB(store).learn("我说话不要客套话, 直接说重点", kind="voice")
        store.resolve_semantic("用户喜欢在周末去公园", confidence=0.8)
        r = eng.recall_all(Cue(text="公园 说重点"), limit=3)
        assert r["events"], "经历层应有结果"
        assert any("公园" in x["claim"] for x in r["semantic"]), "语义层应被召回"
        assert any("客套" in x["text"] for x in r["self"]), "自我知识应被召回"
        store.close()


def test_diary_llm_enrichment():
    """日记 LLM 富化: 有 llm 用它, 没有则回退规则基线。"""
    with tempfile.TemporaryDirectory() as tmp:
        store, ing, eng, life, pers = build(tmp)
        ing.ingest(Observation("用户带我去公园看猫"))
        from shihai.diary import DiaryEngine
        seen = {}
        def llm(prompt):
            seen["prompt"] = prompt
            return "风是暖的, 三花猫把脑袋往我手心里顶。我什么也没说, 只是笑。"
        d = DiaryEngine(store, llm=llm)
        d.close_day()
        row = d.recent(1)[0]
        assert "三花猫" in row["text"], "应使用 llm 生成的内容"
        assert "第一人称日记" in seen["prompt"], "应把富化提示交给模型"
        # 回退
        d2 = DiaryEngine(store)
        assert d2.compose_with_llm() is None, "无 llm 时应返回 None 触发回退"
        store.close()


def test_wiki_ingest_reverse():
    """wiki 反向闭环: 人在 md 里加的内容能写回库。"""
    import os as _os
    with tempfile.TemporaryDirectory() as tmp:
        store, ing, eng, life, pers = build(tmp)
        from shihai.kb import SelfKB
        from shihai.wiki import Wiki
        SelfKB(store).learn("我叫小海", kind="identity")
        w = Wiki(store, root=_os.path.join(tmp, "w"))
        w.sync()
        p = _os.path.join(tmp, "w", "wiki", "self", "identity.md")
        with open(p, "a", encoding="utf-8") as f:
            f.write("- 我是用户亲手写进 wiki 的小海" + chr(10))
        stats = w.ingest_edits()
        assert stats["self_pages"] >= 1
        texts = [r["text"] for r in store.self_knowledge("identity")]
        assert any("亲手写进" in t for t in texts), "wiki 修订未回写: %s" % texts
        store.close()


def test_implant_seed_is_a_prior_not_a_script():
    """植入人格卡: 有起点, 但起点不是终值 —— 记忆会推它, 推不出半径。"""
    with tempfile.TemporaryDirectory() as tmp:
        store, ing, eng, life, pers = build(tmp)
        v, seed, flux = pers.implant(archetype="cautious",
                                     identity_text="我是小海, 从一台旧笔记本上醒来。")
        assert v == 1 and seed["caution"] == 0.72
        card = pers.refresh()
        # 还没有任何经历: 人格必须停在起点, 不能被"没有证据"推向 0.5
        assert abs(card.traits["caution"] - 0.72) < 1e-6, \
            "无记忆时不该漂移: %.3f" % card.traits["caution"]
        assert "从一台旧笔记本上醒来" in card.card, "内核段必须原文进卡"
        assert "v1" in card.card
        store.close()


def test_implant_drift_is_bounded_and_audited():
    """人格被记忆推动, 但单轮 ≤0.03、总量不越半径, 且每条都有归因。"""
    from shihai.persona import STEP_LIMIT
    with tempfile.TemporaryDirectory() as tmp:
        store, ing, eng, life, pers = build(tmp)
        try:
            pers.implant(archetype="curious", flux={"caution": 0.1})
            # 一条真能升格核心的创伤记忆: 性格只由核心记忆推动
            ing.ingest(Observation("用户骂我又错了,说再这样就换掉我,我很害怕"),
                       importance_hint=0.95)
            ing.ingest(Observation("我又想起那次被骂的事,还是后怕"))
            for _ in range(5):
                eng.recall(Cue(text="换掉 害怕 骂"), limit=3)

            prev = store.persona_fields()["caution"]["value"]
            deltas = []
            for _ in range(8):
                life.tick(persona=pers)
                cur = store.persona_fields()["caution"]["value"]
                deltas.append(abs(cur - prev))
                prev = cur
            assert max(deltas) <= STEP_LIMIT + 1e-6, \
                "单轮漂移超上限: %.4f" % max(deltas)
            f = store.persona_fields()
            assert f["caution"]["value"] > 0.35, \
                "记忆指向谨慎, 却没被推动: %.3f" % f["caution"]["value"]
            assert abs(f["caution"]["value"] - f["caution"]["seed"]) <= f["caution"]["cap"] + 1e-6, \
                "越出了可塑半径: %.3f" % f["caution"]["value"]
            log = store.persona_changelog(limit=50)
            assert log, "漂移必须留下账本"
            assert all(r["cause"] in ("recall", "implant", "reflection") for r in log)
            assert any(json.loads(r["evidence"] or "[]") for r in log), \
                "归因应带上证据事件 id"
        finally:
            store.close()


def test_look_only_does_not_move_personality():
    """persist=False(打开仪表盘)不该让人格往前走一步。"""
    with tempfile.TemporaryDirectory() as tmp:
        store, ing, eng, life, pers = build(tmp)
        try:
            pers.implant(archetype="curious")
            ing.ingest(Observation("用户骂我又错了,说再这样就换掉我,我很害怕"),
                       importance_hint=0.95)
            for _ in range(5):
                eng.recall(Cue(text="换掉 害怕"), limit=2)
            life.tick(persona=pers)
            before = store.persona_fields()
            for _ in range(5):
                pers.refresh(persist=False)
            after = store.persona_fields()
            assert all(abs(after[k]["value"] - before[k]["value"]) < 1e-9 for k in before), \
                "只看一眼不该改变人格"
        finally:
            store.close()


def test_reimplant_keeps_history_and_caps_shift():
    """重植入: 版本递增, 旧种子留档; 现值只被拉到新半径边界, 不一键抹平。"""
    with tempfile.TemporaryDirectory() as tmp:
        store, ing, eng, life, pers = build(tmp)
        try:
            pers.implant(traits={"caution": 0.5}, flux={"caution": 0.3})
            v2, seed, _ = pers.implant(traits={"caution": 0.9}, flux={"caution": 0.1})
            assert v2 == 2
            rows = store.conn.execute("SELECT COUNT(*) FROM persona_seed").fetchone()[0]
            assert rows == 2, "旧种子必须留档"
            val = store.persona_fields()["caution"]["value"]
            assert abs(val - 0.8) < 1e-6, "应被拉到新半径边界 0.8, 实际 %.3f" % val
            causes = [r["cause"] for r in store.persona_changelog(limit=10)]
            assert "implant" in causes, "重植入把现值调动了, 就该留账"
        finally:
            store.close()


def test_no_implant_keeps_old_behavior():
    """没植入过的库: 人格完全由记忆决定, 与 v0.6.0 行为一致。"""
    with tempfile.TemporaryDirectory() as tmp:
        store, ing, eng, life, pers = build(tmp)
        ing.ingest(Observation("用户谢谢我,夸我做得很好,我们聊得很开心"),
                   importance_hint=0.9)
        life.tick(persona=pers)
        card = pers.refresh()
        assert card.seed == {} and card.version == 0
        assert card.traits == pers.graph_engine.weave(persist=False).traits, \
            "无种子时应原样采用图谱观测值"
        assert store.conn.execute(
            "SELECT COUNT(*) FROM persona_field").fetchone()[0] == 0
        store.close()


def test_no_fulcrum_rebounds_toward_seed():
    """某维度失去支点后, 现值每轮向种子回弹 —— 遗忘本身就是回正机制。"""
    with tempfile.TemporaryDirectory() as tmp:
        store, ing, eng, life, pers = build(tmp)
        try:
            pers.implant(traits={"self_blame": 0.5, "caution": 0.5},
                         flux={"self_blame": 0.3, "caution": 0.3})
            # 直接造一个"被推高过的现值", 但库里没有任何支点
            store.set_persona_field("self_blame", 0.7, reason="test")
            moved = []
            for _ in range(4):
                pers.refresh()
                moved.append(store.persona_fields()["self_blame"]["value"])
            assert moved[-1] < 0.7, "无支点时现值应向种子回落: %s" % moved
            assert all(b <= a + 1e-9 for a, b in zip([0.7] + moved, moved)), \
                "回弹必须单调向下: %s" % moved
            assert any(r["cause"] == "reflection"
                       for r in store.persona_changelog(limit=20)), \
                "回弹也应留在账本里"
        finally:
            store.close()


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print("PASS %s" % fn.__name__)
        except AssertionError as e:
            failed += 1
            print("FAIL %s: %s" % (fn.__name__, e))
        except Exception as e:
            failed += 1
            print("ERROR %s: %s: %s" % (fn.__name__, type(e).__name__, e))
    print("\n%d/%d passed" % (len(fns) - failed, len(fns)))
    sys.exit(1 if failed else 0)
