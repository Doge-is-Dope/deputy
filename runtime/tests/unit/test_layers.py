"""What the core may import: the session, its tasks and its log stay apart from what a runtime could be without."""

import ast
from pathlib import Path

import computer_use

SOURCE = Path(computer_use.__file__).parent
CORE = {
    "agent.background", "agent.blackboard", "agent.failures", "agent.handover", "agent.history", "agent.inbox", "agent.plan",
    "agent.session", "agent.subagent", "agent.trajectory", "agent.usage", "events", "middleware.chat",
    "middleware.common", "middleware.subagent", "runner", "streaming", "tools.ask_user", "tools.common", "tools.conversations", "tools.plan",
    "tools.tasks",
}
OPTIONAL = (
    "agent.coding_agent", "agent.computer_agent", "agent.review", "computers", "desktop", "execution", "memory",
    "middleware.desktop", "middleware.memory", "middleware.skills", "prompts.coding", "prompts.computer",
    "prompts.memory", "prompts.review", "sandbox", "tools.coding", "tools.desktop",
)

def imported(module: str) -> set[str]:
    """The computer_use modules a module imports, at any level of its code, without the package's name."""
    path = SOURCE / module.replace(".", "/")
    source = path / "__init__.py" if path.is_dir() else path.with_suffix(".py")
    names: set[str] = set()
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("computer_use"):
            package = node.module.removeprefix("computer_use").lstrip(".")
            for alias in node.names:
                whole = f"{package}.{alias.name}".lstrip(".")
                names.add(whole if (SOURCE / f"{whole.replace('.', '/')}.py").exists() else package)
    return names - {""}


def reached(module: str) -> set[str]:
    """Every computer_use module that importing `module` loads, through whichever others."""
    seen, waiting = set(), [module]
    while waiting:
        for name in imported(waiting.pop()) - seen:
            seen.add(name)
            waiting.append(name)
    return seen


def is_optional(module: str) -> bool:
    return any(module == each or module.startswith(f"{each}.") for each in OPTIONAL)


def test_the_core_loads_nothing_optional():
    found = {(module, name) for module in CORE for name in reached(module) if is_optional(name)}

    assert found == set(), "go through a port or an argument instead"
