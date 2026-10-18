# -*- coding: utf-8 -*-
r"""识海的落位与初始化。

本体判断(2026-10-18 定稿):
    Agent 的本体 = 框架 + 记忆, 不是 API。纯 API 每次调用都是新生儿。
    记忆文档(memory 文件)是识海的"投影/物化视图", 每次会话由 context 命令刷新;
    识海 SQLite + 固结循环是"库本体", 以外部服务形态存活在会话之间。
    换 agent 平台只换投影的渲染方式, 本体原样搬走。

落位规则(遵循 2026-10-10 C 盘 AI 数据全量落 F 盘的硬性要求):
    默认 ~/.shihai(跨平台); 本机想放别的盘就设 SHIHAI_HOME 环境变量。
"""

import json
import os

# 识海的家。环境变量可覆盖(测试用), 默认落 MyDeck。
SHIHAI_HOME = os.environ.get("SHIHAI_HOME", os.path.join(os.path.expanduser("~"), ".shihai"))

DB_PATH = os.path.join(SHIHAI_HOME, "shihai.db")          # 识海库本体
TYPOLOGY_PATH = os.path.join(SHIHAI_HOME, "typology.json") # 性格类型连续状态
FREEMODE_PATH = os.path.join(SHIHAI_HOME, "freemode.json") # 自由模式运行态
SERVER_PORT_FILE = os.path.join(SHIHAI_HOME, "server.port")


def ensure_home():
    os.makedirs(SHIHAI_HOME, exist_ok=True)
    return SHIHAI_HOME


def is_initialized():
    return os.path.exists(DB_PATH)


def identity_card():
    """识海的身份信息(首启时写入, 之后只读)。"""
    path = os.path.join(SHIHAI_HOME, "identity.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def write_identity(name, born_note=""):
    ensure_home()
    path = os.path.join(SHIHAI_HOME, "identity.json")
    from .store import utcnow
    card = {"name": name, "born_note": born_note, "born_at": utcnow()}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(card, f, ensure_ascii=False, indent=1)
    return card
