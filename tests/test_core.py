# -*- coding: utf-8 -*-
"""识海回归测试: 这几天修过的每个坑都固化成断言。"""
import os
import sys
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
