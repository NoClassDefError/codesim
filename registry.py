"""Registry of runnable systems: the built-ins plus ``@system`` classes in a user workspace.

Users mark a system class with :func:`system`::

    from codesimpy import system
    from codesimpy.systems import SMIB__GFL_C_F_L

    @system(id="MySMIB", label="SMIB · my variant")
    class MySMIB(SMIB__GFL_C_F_L):
        ...

:func:`discover` imports the decorated files of a workspace folder and returns
a :class:`Registry`. Components need no registration: they are plain
:class:`~codesimpy.core.Device` subclasses that a system creates itself.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TypeVar, overload

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    tomllib = None  # type: ignore[assignment]

T = TypeVar("T", bound=type)

_ATTR = "__codesim__"
USER_MODULE_PREFIX = "codesimpy_user"
_SKIPPED_DIRECTORIES = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", ".tox", ".mypy_cache", ".pytest_cache",
    "node_modules", "__pycache__", "build", "dist", "site-packages",
}


@dataclass(frozen=True)
class Meta:
    """What ``@system`` records on a class."""
    id: str
    label: str
    category: str = ""
    description: str = ""
    file: str = ""
    line: int = 0


@overload
def system(cls: T, /) -> T: ...
@overload
def system(
    *, id: str | None = None, label: str | None = None,
    category: str = "", description: str | None = None,
) -> Callable[[T], T]: ...
def system(cls=None, /, *, id=None, label=None, category="", description=None):
    """Mark a :class:`~codesimpy.core.System` subclass as runnable from the frontend.

    Use it bare (``@system``) or with metadata (``@system(id=..., label=...)``).
    ``id`` defaults to the class name and must be unique among all systems.
    """
    def apply(target):
        from .core import System

        if not (isinstance(target, type) and issubclass(target, System)):
            raise TypeError(f"@system must decorate a System subclass, got {target!r}")
        if inspect.isabstract(target):
            missing = ", ".join(sorted(target.__abstractmethods__))
            raise TypeError(f"@system {target.__name__} is abstract; implement: {missing}")
        if not callable(getattr(target, "defaultParameters", None)):
            raise TypeError(f"@system {target.__name__} must define defaultParameters(overrides)")
        try:
            file = inspect.getsourcefile(target) or ""
            line = inspect.getsourcelines(target)[1]
        except (OSError, TypeError):  # no source available (e.g. compiled)
            file, line = "", 0
        systemId = id or target.__name__
        setattr(target, _ATTR, Meta(
            id=systemId,
            label=label or systemId,
            category=category,
            description=(
                description if description is not None
                else (inspect.getdoc(target) or "").split("\n")[0]
            ),
            file=file,
            line=line,
        ))
        return target

    return apply(cls) if cls is not None else apply


def meta_of(cls: type) -> Meta | None:
    """The class's own ``@system`` metadata; subclasses do not inherit registration."""
    return cls.__dict__.get(_ATTR)


@dataclass
class SystemEntry:
    id: str
    cls: type
    source: str  # "builtin" | "workspace"
    label: str = ""
    category: str = ""
    description: str = ""
    file: str = ""
    line: int = 0

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id, "label": self.label, "category": self.category,
            "description": self.description, "source": self.source,
            "file": self.file, "line": self.line,
        }


@dataclass
class Registry:
    systems: dict[str, SystemEntry] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    workspace: str | None = None

    def add(self, entry: SystemEntry) -> None:
        existing = self.systems.get(entry.id)
        if existing is not None and existing.cls is not entry.cls:
            where = existing.file or existing.source
            raise ValueError(f"system id {entry.id!r} is already registered by {where}")
        self.systems[entry.id] = entry

    def describe(self) -> dict[str, Any]:
        return {
            "workspace": self.workspace,
            "systems": [entry.describe() for entry in self.systems.values()],
            "errors": list(self.errors),
        }


def _uses_system_decorator(path: Path) -> bool:
    """True when the file defines a class decorated with ``system`` (parsed, never run)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    except (SyntaxError, UnicodeDecodeError, ValueError):
        return True  # import it so the user sees the real error
    except OSError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if isinstance(target, ast.Attribute):
                name = target.attr
            elif isinstance(target, ast.Name):
                name = target.id
            else:
                continue
            if name == "system":
                return True
    return False


def _workspace_config(workspace: Path) -> dict[str, Any]:
    pyproject = workspace / "pyproject.toml"
    if tomllib is None or not pyproject.is_file():
        return {}
    with pyproject.open("rb") as stream:
        return tomllib.load(stream).get("tool", {}).get("codesim", {})


def find_user_files(workspace: str | Path) -> list[Path]:
    """Files to import: ``[tool.codesim] systems`` globs, else every file using ``@system``."""
    root = Path(workspace).resolve()
    config = _workspace_config(root)
    patterns = config.get("systems")
    if patterns:
        files = {path.resolve() for pattern in patterns for path in root.glob(pattern) if path.is_file()}
        files -= {path.resolve() for pattern in config.get("exclude", []) for path in root.glob(pattern)}
        return sorted(path for path in files if path.suffix == ".py")
    found = []
    for path in root.rglob("*.py"):
        parts = path.relative_to(root).parts
        if any(part in _SKIPPED_DIRECTORIES or part.startswith(".") for part in parts[:-1]):
            continue
        if _uses_system_decorator(path):
            found.append(path.resolve())
    return sorted(found)


def _module_name(path: Path, workspace: Path) -> str:
    parts = path.relative_to(workspace).with_suffix("").parts
    safe = ["".join(c if c.isalnum() or c == "_" else "_" for c in part) for part in parts]
    return ".".join([USER_MODULE_PREFIX, *safe])


def purge_user_modules() -> None:
    """Forget previously imported workspace files so the next import reads them again."""
    for name in [name for name in sys.modules if name == USER_MODULE_PREFIX
                 or name.startswith(USER_MODULE_PREFIX + ".")]:
        del sys.modules[name]


def import_user_file(path: Path, workspace: Path):
    if str(workspace) not in sys.path:
        sys.path.insert(0, str(workspace))  # lets user files import their sibling modules
    name = _module_name(path, workspace)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _builtin_entries():
    from . import systems as builtin

    for name in builtin.__all__:
        cls = getattr(builtin, name)
        meta = meta_of(cls)
        yield SystemEntry(
            id=meta.id if meta else name, cls=cls, source="builtin",
            label=meta.label if meta else name,
            category=meta.category if meta else "",
            description=meta.description if meta else (inspect.getdoc(cls) or "").split("\n")[0],
        )


def discover(workspace: str | Path | None = None) -> Registry:
    """Built-in systems, plus the ``@system`` classes found in ``workspace``."""
    registry = Registry()
    for entry in _builtin_entries():
        registry.add(entry)
    if workspace is None:
        return registry

    root = Path(workspace).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"workspace is not a directory: {root}")
    registry.workspace = str(root)
    purge_user_modules()
    try:
        files = find_user_files(root)
    except Exception as error:  # e.g. malformed pyproject.toml
        registry.errors.append(_error(root / "pyproject.toml", error))
        return registry
    for path in files:
        try:
            module = import_user_file(path, root)
            for obj in list(vars(module).values()):
                if not isinstance(obj, type) or obj.__module__ != module.__name__:
                    continue
                meta = meta_of(obj)
                if meta is None:
                    continue
                registry.add(SystemEntry(
                    id=meta.id, cls=obj, source="workspace", label=meta.label,
                    category=meta.category, description=meta.description,
                    file=meta.file or str(path), line=meta.line,
                ))
        except Exception as error:
            registry.errors.append(_error(path, error))
    return registry


def _error(path: Path, error: BaseException) -> dict[str, Any]:
    line = 0
    if isinstance(error, SyntaxError) and error.lineno:
        line = error.lineno
    else:
        for frame in reversed(traceback.extract_tb(error.__traceback__)):
            if Path(frame.filename).resolve() == path.resolve():
                line = frame.lineno or 0
                break
    return {
        "file": str(path),
        "line": line,
        "error": f"{type(error).__name__}: {error}",
        "traceback": "".join(traceback.format_exception(type(error), error, error.__traceback__)),
    }
