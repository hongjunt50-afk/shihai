# -*- coding: utf-8 -*-
r"""识海的落位与初始化。

本体判断(2026-10-18 定稿):
    Agent 的本体 = 框架 + 记忆, 不是 API。纯 API 每次调用都是新生儿。
    记忆文档(memory 文件)是识海的"投影/物化视图", 每次会话由 context 命令刷新;
    识海 SQLite + 固结循环是"库本体", 以外部服务形态存活在会话之间。
    换 agent 平台只换投影的渲染方式, 本体原样搬走。

落位规则:
    默认 ~/.shihai(跨平台); 想放别的盘就设 SHIHAI_HOME 环境变量。
"""

import json
import os

# 识海的家。环境变量可覆盖(测试/多实例用), 默认 ~/.shihai。
#
# 2026-10-29 改成惰性解析。旧版在模块导入时就把路径算成常量, 于是
# `os.environ["SHIHAI_HOME"] = tmp` 在导入之后再设完全无效 —— 测试、
# 临时实例、多 agent 全部静默写到真实库(~/.shihai)。实测代价: 冒烟测试与
# 单元测试往用户的记忆本体里塞了假事件, 还把一条 voice 的稳固度顶上去了。
# 现在每次取路径都重新读环境变量, 下面四个名字保持可用(模块级 __getattr__)。

_DEFAULT_HOME = os.path.join(os.path.expanduser("~"), ".shihai")

_FILES = {
    "DB_PATH": "shihai.db",              # 识海库本体
    "TYPOLOGY_PATH": "typology.json",    # 性格类型连续状态
    "FREEMODE_PATH": "freemode.json",    # 自由模式运行态
    "SERVER_PORT_FILE": "server.port",
}


def home():
    return os.environ.get("SHIHAI_HOME") or _DEFAULT_HOME


def __getattr__(name):
    """让 H.SHIHAI_HOME / H.DB_PATH 这类旧写法仍然可用, 但每次现算。"""
    if name == "SHIHAI_HOME":
        return home()
    if name in _FILES:
        return os.path.join(home(), _FILES[name])
    raise AttributeError(name)


def ensure_home():
    os.makedirs(home(), exist_ok=True)
    return home()


def is_initialized():
    return os.path.exists(os.path.join(home(), _FILES["DB_PATH"]))


def identity_card():
    """识海的身份信息(首启时写入, 之后只读)。"""
    path = os.path.join(home(), "identity.json")
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
