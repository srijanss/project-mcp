"""Pytest test discovery and analysis."""

import ast
from pathlib import Path


def _is_test_file(path: str) -> bool:
    """Check if a file matches pytest test naming conventions."""
    name = Path(path).name
    return name.startswith("test_") and name.endswith(".py") or (
        name.endswith("_test.py")
    )


def discover_tests(path: str, source: str) -> list[dict]:
    """Discover pytest tests (functions and classes) in a Python source file.

    Args:
        path: File path
        source: Source code string

    Returns:
        List of test dicts with name, kind, qualified_name, location info.
    """
    if not _is_test_file(path):
        return []

    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return []

    module_name = _module_qualified_name(path)
    tests = []

    def visit_body(body, qualified_prefix):
        for node in body:
            if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                class_qualified = f"{qualified_prefix}.{node.name}"
                # Class itself can be a test container
                tests.append({
                    "name": node.name,
                    "qualified_name": class_qualified,
                    "kind": "test_class",
                    "start_line": node.lineno,
                    "end_line": node.end_lineno,
                })
                # Methods in Test* class
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if item.name.startswith("test_"):
                            method_qualified = f"{class_qualified}.{item.name}"
                            tests.append({
                                "name": item.name,
                                "qualified_name": method_qualified,
                                "kind": "test_method",
                                "start_line": item.lineno,
                                "end_line": item.end_lineno,
                            })
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test_"):
                    func_qualified = f"{qualified_prefix}.{node.name}"
                    tests.append({
                        "name": node.name,
                        "qualified_name": func_qualified,
                        "kind": "test_function",
                        "start_line": node.lineno,
                        "end_line": node.end_lineno,
                    })

    visit_body(tree.body, module_name)
    return tests


def _module_qualified_name(path: str) -> str:
    module_path = Path(path).with_suffix("")
    return ".".join(module_path.parts)


def extract_test_imports(path: str, source: str) -> list[dict]:
    """Extract import statements from a test file.

    Used to associate tests with the source modules they import.

    Args:
        path: File path
        source: Source code string

    Returns:
        List of import dicts with module name and imported symbols.
    """
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return []

    imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append({
                    "module": node.module,
                    "level": node.level,
                    "names": [alias.name for alias in node.names],
                })
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append({
                    "module": alias.name,
                    "level": 0,
                    "names": [alias.name],
                })

    return imports


def find_test_source_refs(path: str, source: str) -> list[dict]:
    """Find source module symbols referenced by a test.

    Analyzes test code to identify what functions/classes it calls or uses.
    Not currently called by build_test_relationships: it pairs every
    referenced name with every imported module rather than the specific
    module that defines it, so it isn't reliable enough yet to feed the
    "symbol_reference" evidence type used there.

    Args:
        path: Test file path
        source: Test source code

    Returns:
        List of references with module and symbol names.
    """
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return []

    refs = []

    # Collect imports to understand what this test depends on
    imported_modules = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_modules[node.module] = node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules[alias.name] = alias.name

    # Walk AST to find Name nodes (references to imported symbols)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            # Simple heuristic: if a name is referenced and it's not a builtin, it might be from source
            refs.append({
                "symbol": node.id,
                "modules": list(imported_modules.values()),
            })

    return refs


def infer_tested_module(test_path: str) -> str | None:
    """Infer which source module is tested based on naming convention.

    test_foo.py -> foo module
    foo_test.py -> foo module

    Args:
        test_path: Test file path

    Returns:
        Inferred module name or None if no convention match.
    """
    filename = Path(test_path).stem  # Remove .py extension

    # test_* convention
    if filename.startswith("test_"):
        return filename[5:]  # Remove "test_" prefix

    # *_test convention
    if filename.endswith("_test"):
        return filename[:-5]  # Remove "_test" suffix

    return None


def build_test_relationships(path: str, source: str) -> list[dict]:
    """Combine test-to-source evidence into confidence-scored relationships.

    Only counts a module as related when there is real evidence (a direct
    import) — bare local names referenced in the test body (e.g. a plain
    variable like ``expected``) are not source-module evidence and must not
    show up as relationship targets.

    Args:
        path: Test file path
        source: Test source code

    Returns:
        List of dicts with target_module, confidence, and evidence.
    """
    if not _is_test_file(path):
        return []

    imports = extract_test_imports(path, source)

    imported_modules = []
    seen_modules = set()
    for imp in imports:
        module = imp.get("module")
        if not module or imp.get("level", 0) != 0 or module in seen_modules:
            continue
        seen_modules.add(module)
        imported_modules.append(module)

    relationships = [
        {
            "target_module": module,
            "confidence": "high",
            "evidence": ["direct_import"],
        }
        for module in imported_modules
    ]
    if relationships:
        return relationships

    inferred = infer_tested_module(path)
    if inferred:
        relationships.append({
            "target_module": inferred,
            "confidence": "low",
            "evidence": ["naming_convention"],
        })
    return relationships


def classify_test_type(path: str) -> str:
    """Classify test type based on directory structure.

    Args:
        path: File path of the test

    Returns:
        Test type: 'unit', 'integration', 'e2e', or 'unknown'
    """
    normalized = path.replace("\\", "/")

    if "/e2e/" in normalized or "_e2e" in path:
        return "e2e"
    elif "/integration/" in normalized or "_integration" in path:
        return "integration"
    elif "/unit/" in normalized or normalized.startswith("tests/") or normalized.startswith("test_"):
        return "unit"

    return "unknown"
