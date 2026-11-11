"""枚举取值域 —— 单一注册表（规范第 3 节）。禁止在业务代码里散落字符串。"""
from enum import Enum


class State(str, Enum):
    FULL = "FULL"
    NORMAL = "NORMAL"
    CONDENSED = "CONDENSED"
    VESTIGE = "VESTIGE"
    DELETED = "DELETED"


class NodeKind(str, Enum):
    ATOM = "ATOM"
    ABSTRACT = "ABSTRACT"
    SCHEMA = "SCHEMA"


class EdgeRelation(str, Enum):
    ASSOCIATED = "ASSOCIATED"
    IS_A = "IS_A"
    PART_OF = "PART_OF"
    CAUSES = "CAUSES"
    BEFORE = "BEFORE"
    CONTRASTS = "CONTRASTS"
    SEQUENCE = "SEQUENCE"
    MEMBER_OF = "MEMBER_OF"


class EdgeState(str, Enum):
    ACTIVE = "ACTIVE"
    DORMANT = "DORMANT"
    PRUNED = "PRUNED"


class EventType(str, Enum):
    CREATE = "CREATE"
    REINFORCE = "REINFORCE"
    DECAY = "DECAY"
    COMPRESS = "COMPRESS"
    MERGE = "MERGE"
    SPLIT = "SPLIT"
    DELETE = "DELETE"
    PIN = "PIN"
    NORMALIZE = "NORMALIZE"
    RESTORE = "RESTORE"


class SourceKind(str, Enum):
    HUMAN = "HUMAN"
    AI = "AI"
    IMPORT = "IMPORT"
    SYSTEM = "SYSTEM"


# 状态档位（用于判断"升档/降档"）
STATE_LEVEL = {
    State.DELETED: 0,
    State.VESTIGE: 1,
    State.CONDENSED: 2,
    State.NORMAL: 3,
    State.FULL: 4,
}
