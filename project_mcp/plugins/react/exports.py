"""What a react source file exports."""
import re

from project_mcp.plugins.react.usages import _without_comments

_DEFAULT_DECLARATION = re.compile(
    r"^\s*export\s+default\s+(?:async\s+)?(?:function\s*\*?|class)\s+([A-Za-z_$][\w$]*)",
    re.MULTILINE,
)
# `export default Name;` or a one-line wrapper such as `memo(Name)` or `connect(a)(Name)`
_DEFAULT_EXPRESSION = re.compile(
    r"^\s*export\s+default\s+(?:[\w$.]+\s*\(.*?)?([A-Za-z_$][\w$]*)\s*\)*\s*;?[ \t]*$",
    re.MULTILINE,
)
_DEFAULT_ALIAS = re.compile(r"(?<![\w$])([A-Za-z_$][\w$]*)\s+as\s+default\b")


def default_export_name(source: str) -> str | None:
    """The local name a file exports as its default, if statically visible."""
    code = _without_comments(source)
    for pattern in (_DEFAULT_DECLARATION, _DEFAULT_EXPRESSION, _DEFAULT_ALIAS):
        match = pattern.search(code)
        if match:
            return match[1]
    return None
