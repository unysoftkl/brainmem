"""领域异常（规范第 8 节）。MCP 层映射为结构化错误码。"""


class BrainMemError(Exception):
    code = "ERR_INTERNAL"


class ValidationError(BrainMemError):
    code = "ERR_VALIDATION"


class TooLongError(BrainMemError):
    code = "ERR_TOO_LONG"


class NotFoundError(BrainMemError):
    code = "ERR_NOT_FOUND"


class ConflictError(BrainMemError):
    code = "ERR_CONFLICT"


class BudgetError(BrainMemError):
    code = "ERR_BUDGET"
