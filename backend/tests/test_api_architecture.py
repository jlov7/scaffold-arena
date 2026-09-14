from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _imports_main(path: Path) -> bool:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            alias.name == "main" or alias.name.startswith("main.") for alias in node.names
        ):
            return True
        if isinstance(node, ast.ImportFrom) and node.module and (
            node.module == "main" or node.module.startswith("main.")
        ):
            return True
    return False


def test_http_composition_stays_in_main_and_business_routes_stay_in_routers() -> None:
    main_path = BACKEND / "main.py"
    source = main_path.read_text()
    tree = ast.parse(source)
    assert len(source.splitlines()) < 400
    assert "BaseModel" not in source
    assert not any(
        isinstance(node, ast.ClassDef) and node.name.endswith("Request")
        for node in ast.walk(tree)
    )

    app_route_decorators = [
        decorator
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for decorator in node.decorator_list
        if isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and isinstance(decorator.func.value, ast.Name)
        and decorator.func.value.id == "app"
        and decorator.func.attr in {"get", "post", "put", "patch", "delete"}
    ]
    assert len(app_route_decorators) <= 1


def test_router_and_lifecycle_modules_do_not_depend_on_main() -> None:
    bounded_modules = [
        *(BACKEND / "api").glob("*.py"),
        BACKEND / "core" / "run_engine.py",
        BACKEND / "core" / "run_lifecycle.py",
    ]
    assert not [path for path in bounded_modules if _imports_main(path)]
    assert len((BACKEND / "core" / "run_engine.py").read_text().splitlines()) < 450
