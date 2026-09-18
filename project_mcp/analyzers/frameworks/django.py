"""Django framework analyzer — detects models, views, migrations, and other Django patterns."""

from pathlib import Path


def detect_django_models(symbols: list[dict], relationships: list[dict]) -> list[dict]:
    """Identify symbols that are Django model classes.

    A model is a class that inherits from django.db.models.Model or models.Model.

    Args:
        symbols: List of parsed symbols with kind, bases, qualified_name, etc.
        relationships: List of inheritance relationships (unused but available).

    Returns:
        List of dicts with qualified_name and framework_kind="django_model" for models.
    """
    model_bases = {"django.db.models.Model", "models.Model"}
    result = []

    for symbol in symbols:
        if symbol.get("kind") != "class":
            continue
        bases = symbol.get("bases", [])
        if any(base in model_bases for base in bases):
            result.append({
                "qualified_name": symbol["qualified_name"],
                "framework_kind": "django_model",
            })

    return result


def detect_migrations(files: list[dict]) -> list[dict]:
    """Identify files in Django migrations directories.

    Args:
        files: List of files with path, kind, language, etc.

    Returns:
        List of files with framework_kind="django_migration" for migration files.
    """
    result = []
    for file in files:
        path_str = file.get("path", "")
        # Normalize path to handle both Unix and Windows separators
        normalized = path_str.replace("\\", "/")
        if "/migrations/" in normalized:
            result.append({
                "path": path_str,
                "framework_kind": "django_migration",
            })
    return result


def detect_views(symbols: list[dict]) -> list[dict]:
    """Identify Django view functions and classes.

    A view is a function/class in a views.py file or with View in its base classes.

    Args:
        symbols: List of parsed symbols with kind, bases, qualified_name, etc.

    Returns:
        List of dicts with qualified_name and framework_kind="django_view" for views.
    """
    result = []
    view_bases = {"View", "django.views.View", "generic.View"}

    for symbol in symbols:
        kind = symbol.get("kind")
        qualified_name = symbol.get("qualified_name", "")

        # Check if in views.py file or inherits from View
        in_views_file = ".views." in qualified_name
        has_view_base = any(base in view_bases for base in symbol.get("bases", []))

        if in_views_file or has_view_base:
            if kind in ("function", "class"):
                result.append({
                    "qualified_name": qualified_name,
                    "framework_kind": "django_view",
                })

    return result


def detect_django_services(files: list[dict]) -> list[dict]:
    """Identify Django service/query modules (services.py, queries.py, etc.).

    These modules typically contain business logic and database queries.

    Args:
        files: List of files with path, language, etc.

    Returns:
        List of files with framework_kind="django_service" for service files.
    """
    service_names = {"services.py", "queries.py", "managers.py", "helpers.py"}
    result = []
    for file in files:
        path_str = file.get("path", "")
        # Check filename after either separator type
        filename = path_str.replace("\\", "/").split("/")[-1]
        if filename in service_names:
            result.append({
                "path": path_str,
                "framework_kind": "django_service",
            })
    return result


def detect_django_urls(files: list[dict]) -> list[dict]:
    """Identify Django URL configuration files (urls.py).

    Args:
        files: List of files with path, language, etc.

    Returns:
        List of files with framework_kind="django_urls" for urls.py files.
    """
    result = []
    for file in files:
        path_str = file.get("path", "")
        # Check filename after either separator type
        filename = path_str.replace("\\", "/").split("/")[-1]
        if filename == "urls.py":
            result.append({
                "path": path_str,
                "framework_kind": "django_urls",
            })
    return result


def detect_django_apps(files: list[dict]) -> list[dict]:
    """Identify Django app directories by presence of apps.py file.

    Args:
        files: List of files with path, language, etc.

    Returns:
        List of files with framework_kind="django_app" for Python apps.py files.
    """
    result = []
    for file in files:
        path_str = file.get("path", "")
        language = file.get("language", "")
        # Check filename after either separator type
        filename = path_str.replace("\\", "/").split("/")[-1]
        if filename == "apps.py" and language == "python":
            result.append({
                "path": path_str,
                "framework_kind": "django_app",
            })
    return result


def enrich_django_metadata(
    symbols: list[dict], files: list[dict], relationships: list[dict]
) -> list[dict]:
    """Enrich symbols and files with Django framework metadata.

    Combines all detectors (models, views, migrations, apps, urls, services) into a single enrichment pass.

    Args:
        symbols: List of parsed symbols.
        files: List of project files.
        relationships: List of symbol relationships.

    Returns:
        Combined list of enriched entities with framework_kind set.
    """
    result = []
    result.extend(detect_django_models(symbols, relationships))
    result.extend(detect_views(symbols))
    result.extend(detect_migrations(files))
    result.extend(detect_django_apps(files))
    result.extend(detect_django_urls(files))
    result.extend(detect_django_services(files))
    return result
