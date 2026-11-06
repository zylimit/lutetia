# risk: high
"""Python 3.9 兼容与密钥前缀机器闸。"""
import ast
import subprocess
from pathlib import Path
from typing import Iterator, List, Tuple

ROOT = Path(__file__).resolve().parents[1]


def _py_files() -> List[Path]:
    files = list((ROOT / "lutetia").rglob("*.py")) + list((ROOT / "tests").glob("*.py"))
    return sorted(files)


def _trees() -> Iterator[Tuple[Path, ast.AST]]:
    for path in _py_files():
        src = path.read_text(encoding="utf-8")
        yield path, ast.parse(src, filename=str(path), feature_version=(3, 9))


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def test_syntax_is_py39():
    errors = []
    for path in _py_files():
        src = path.read_text(encoding="utf-8")
        try:
            ast.parse(src, filename=str(path), feature_version=(3, 9))
        except SyntaxError as exc:
            errors.append("%s: %s" % (_rel(path), exc))
    assert errors == [], "非 3.9 语法: %s" % errors


def _has_bitor(node: ast.AST) -> bool:
    return any(
        isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr) for n in ast.walk(node)
    )


def test_no_pep604_unions_in_annotations():
    hits = []
    for path, tree in _trees():
        for node in ast.walk(tree):
            anns = []
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                a = node.args
                for arg in a.posonlyargs + a.args + a.kwonlyargs + [a.vararg, a.kwarg]:
                    if arg is not None and arg.annotation is not None:
                        anns.append(arg.annotation)
                if node.returns is not None:
                    anns.append(node.returns)
            elif isinstance(node, ast.AnnAssign):
                anns.append(node.annotation)
            for ann in anns:
                if _has_bitor(ann):
                    hits.append("%s:%d" % (_rel(path), ann.lineno))
    assert hits == [], "注解里有 PEP 604 联合: %s" % hits


_TYPING_BAD = {"TypeAlias", "ParamSpec", "Self", "Concatenate"}


def test_no_py310_stdlib_names():
    hits = []
    for path, tree in _trees():
        for node in ast.walk(tree):
            where = "%s:%d" % (_rel(path), getattr(node, "lineno", 0))
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "tomllib":
                        hits.append(where + " import tomllib")
            elif isinstance(node, ast.ImportFrom):
                if node.module == "tomllib":
                    hits.append(where + " from tomllib")
                for alias in node.names:
                    if node.module == "typing" and alias.name in _TYPING_BAD:
                        hits.append(where + " typing." + alias.name)
                    if node.module == "itertools" and alias.name == "pairwise":
                        hits.append(where + " itertools.pairwise")
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if node.value.id == "typing" and node.attr in _TYPING_BAD:
                    hits.append(where + " typing." + node.attr)
                if node.value.id == "itertools" and node.attr == "pairwise":
                    hits.append(where + " itertools.pairwise")
    assert hits == [], "3.10+ 标准库名: %s" % hits


def test_no_credential_prefixes_in_repo():
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    ).stdout
    needles = ["Hua" + "wei@", "li" + "wei@"]
    hits = []
    for name in out.decode("utf-8").split("\0"):
        if not name:
            continue
        try:
            text = (ROOT / name).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        if any(n in text for n in needles):
            hits.append(name)
    assert hits == [], "文件含账号密码前缀: %s" % hits
