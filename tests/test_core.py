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
