"""Tests for Django framework analyzer."""

from pathlib import Path

from project_mcp.plugins.django.metadata import (
    detect_django_apps,
    detect_django_models,
    detect_django_services,
    detect_django_urls,
    detect_migrations,
    detect_views,
    enrich_django_metadata,
)


def test_enrich_django_metadata_handles_empty_symbol_and_file_lists():
    """Empty symbols/files input should return an empty result, not crash."""
    result = enrich_django_metadata([], [], [])

    assert result == []


def test_detect_django_models_tolerates_dynamic_base_markers():
    """A computed base (parser emits a dict marker) must not crash detection."""
    dynamic_base = {"dynamic": True, "expression": "make_base()"}
    symbols = [
        {"qualified_name": "app.Computed", "kind": "class", "bases": [dynamic_base]},
        {
            "qualified_name": "app.Mixed",
            "kind": "class",
            "bases": [dynamic_base, "models.Model"],
        },
    ]

    result = detect_django_models(symbols, [])

    assert result == [
        {"qualified_name": "app.Mixed", "framework_kind": "django_model"}
    ]


def test_detect_django_models_skips_symbols_missing_qualified_name():
    """A matching class symbol with no qualified_name key should be skipped, not crash."""
    symbols = [
        {
            "name": "User",
            "kind": "class",
            "start_line": 1,
            "end_line": 5,
            "visibility": "public",
            "bases": ["models.Model"],
        }
    ]

    result = detect_django_models(symbols, [])

    assert result == []


def test_detect_django_models_identifies_model_subclass():
    """Django analyzer should identify classes inheriting from models.Model."""
    symbols = [
        {
            "name": "User",
            "qualified_name": "myapp.models.User",
            "kind": "class",
            "start_line": 1,
            "end_line": 5,
            "visibility": "public",
            "bases": ["models.Model"],
        }
    ]
    relationships = [
        {
            "source": "myapp.models.User",
            "target": "django.db.models.Model",
            "kind": "inherits",
        }
    ]

    result = detect_django_models(symbols, relationships)

    assert len(result) == 1
    assert result[0]["qualified_name"] == "myapp.models.User"
    assert result[0]["framework_kind"] == "django_model"


def test_detect_django_models_handles_explicit_null_bases():
    """A symbol with bases explicitly None (not missing) should not crash."""
    symbols = [
        {
            "name": "User",
            "qualified_name": "myapp.models.User",
            "kind": "class",
            "start_line": 1,
            "end_line": 5,
            "visibility": "public",
            "bases": None,
        }
    ]

    result = detect_django_models(symbols, [])

    assert result == []


def test_detect_django_models_ignores_non_model_classes():
    """Non-model classes should not be marked as django_model."""
    symbols = [
        {
            "name": "User",
            "qualified_name": "myapp.models.User",
            "kind": "class",
            "start_line": 1,
            "end_line": 5,
            "visibility": "public",
            "bases": ["BaseUser"],
        },
        {
            "name": "serializers",
            "qualified_name": "myapp.serializers",
            "kind": "module",
            "start_line": 1,
            "end_line": 10,
            "visibility": "public",
            "bases": [],
        },
    ]
    relationships = []

    result = detect_django_models(symbols, relationships)

    assert len(result) == 0


def test_detect_django_models_handles_django_db_models_fully_qualified_base():
    """Should identify models using fully-qualified django.db.models.Model base."""
    symbols = [
        {
            "name": "Product",
            "qualified_name": "shop.models.Product",
            "kind": "class",
            "start_line": 10,
            "end_line": 20,
            "visibility": "public",
            "bases": ["django.db.models.Model"],
        }
    ]
    relationships = []

    result = detect_django_models(symbols, relationships)

    assert len(result) == 1
    assert result[0]["qualified_name"] == "shop.models.Product"
    assert result[0]["framework_kind"] == "django_model"


def test_detect_migrations_marks_files_in_migrations_directory():
    """Files in migrations/ directories should be marked as django_migration."""
    files = [
        {"path": "myapp/migrations/__init__.py", "kind": "source", "language": "python"},
        {"path": "myapp/migrations/0001_initial.py", "kind": "source", "language": "python"},
        {"path": "myapp/migrations/0002_add_field.py", "kind": "source", "language": "python"},
        {"path": "myapp/models.py", "kind": "source", "language": "python"},
    ]

    result = detect_migrations(files)

    migration_paths = [r["path"] for r in result if r.get("framework_kind") == "django_migration"]
    assert len(migration_paths) == 3
    assert "myapp/migrations/__init__.py" in migration_paths
    assert "myapp/migrations/0001_initial.py" in migration_paths
    assert "myapp/migrations/0002_add_field.py" in migration_paths


def test_detect_views_handles_explicit_null_bases():
    """A symbol with bases explicitly None (not missing) should not crash."""
    symbols = [
        {
            "name": "helper",
            "qualified_name": "myapp.utils.helper",
            "kind": "function",
            "start_line": 1,
            "end_line": 5,
            "visibility": "public",
            "bases": None,
        }
    ]

    result = detect_views(symbols)

    assert result == []


def test_detect_views_tolerates_dynamic_base_markers():
    """A computed base (parser emits a dict marker) must not crash view detection."""
    dynamic_base = {"dynamic": True, "expression": "make_base()"}
    symbols = [
        {"qualified_name": "app.Computed", "kind": "class", "bases": [dynamic_base]},
        {
            "qualified_name": "app.Mixed",
            "kind": "class",
            "bases": [dynamic_base, "View"],
        },
    ]

    result = detect_views(symbols)

    assert result == [{"qualified_name": "app.Mixed", "framework_kind": "django_view"}]


def test_detect_views_identifies_function_named_view():
    """Functions with 'view' suffix or pattern should be marked as django_view."""
    symbols = [
        {
            "name": "user_list",
            "qualified_name": "myapp.views.user_list",
            "kind": "function",
            "start_line": 5,
            "end_line": 15,
            "visibility": "public",
        },
        {
            "name": "ProductDetailView",
            "qualified_name": "myapp.views.ProductDetailView",
            "kind": "class",
            "start_line": 20,
            "end_line": 30,
            "visibility": "public",
            "bases": ["View"],
        },
        {
            "name": "helper",
            "qualified_name": "myapp.utils.helper",
            "kind": "function",
            "start_line": 1,
            "end_line": 5,
            "visibility": "public",
        },
    ]

    result = detect_views(symbols)

    view_names = [r["qualified_name"] for r in result if r.get("framework_kind") == "django_view"]
    assert len(view_names) == 2
    assert "myapp.views.user_list" in view_names
    assert "myapp.views.ProductDetailView" in view_names
    assert "myapp.utils.helper" not in view_names


def test_enrich_django_metadata_combines_all_detectors():
    """Enricher should combine models, views, and migrations detection."""
    symbols = [
        {
            "name": "User",
            "qualified_name": "myapp.models.User",
            "kind": "class",
            "bases": ["models.Model"],
        },
        {
            "name": "user_list",
            "qualified_name": "myapp.views.user_list",
            "kind": "function",
        },
    ]
    files = [
        {"path": "myapp/migrations/0001_initial.py"},
    ]
    relationships = []

    result = enrich_django_metadata(symbols, files, relationships)

    assert len(result) >= 3
    models = [r for r in result if r.get("framework_kind") == "django_model"]
    views = [r for r in result if r.get("framework_kind") == "django_view"]
    migrations = [r for r in result if r.get("framework_kind") == "django_migration"]

    assert len(models) == 1
    assert len(views) == 1
    assert len(migrations) == 1


def test_detect_django_apps_identifies_apps_with_apps_py():
    """Django apps should be identified by presence of apps.py."""
    files = [
        {"path": "myapp/apps.py", "language": "python"},
        {"path": "myapp/models.py", "language": "python"},
        {"path": "another_app/apps.py", "language": "python"},
        {"path": "utils/helpers.py", "language": "python"},
    ]

    result = detect_django_apps(files)

    app_paths = [r["path"] for r in result if r.get("framework_kind") == "django_app"]
    assert len(app_paths) == 2
    assert "myapp/apps.py" in app_paths
    assert "another_app/apps.py" in app_paths
    assert "utils/helpers.py" not in app_paths


def test_detect_django_apps_handles_nested_and_non_python_apps_py():
    """Should only detect Python apps.py files."""
    files = [
        {"path": "myapp/apps.py", "language": "python"},
        {"path": "nested/deep/app/apps.py", "language": "python"},
        {"path": "docs/apps.py", "language": "markdown"},
        {"path": "app_backup/apps.py.bak", "language": "python"},
    ]

    result = detect_django_apps(files)

    app_paths = [r["path"] for r in result if r.get("framework_kind") == "django_app"]
    assert len(app_paths) == 2
    assert "myapp/apps.py" in app_paths
    assert "nested/deep/app/apps.py" in app_paths
    assert "docs/apps.py" not in app_paths
    assert "app_backup/apps.py.bak" not in app_paths


def test_detect_django_urls_identifies_urls_files():
    """URL configuration files (urls.py) should be identified."""
    files = [
        {"path": "myproject/urls.py"},
        {"path": "myapp/urls.py"},
        {"path": "myapp/views.py"},
        {"path": "api/v1/urls.py"},
    ]

    result = detect_django_urls(files)

    url_paths = [r["path"] for r in result if r.get("framework_kind") == "django_urls"]
    assert len(url_paths) == 3
    assert "myproject/urls.py" in url_paths
    assert "myapp/urls.py" in url_paths
    assert "api/v1/urls.py" in url_paths
    assert "myapp/views.py" not in url_paths


def test_detect_django_urls_handles_root_and_non_python_urls():
    """Should handle root-level urls.py and ignore non-Python files."""
    files = [
        {"path": "urls.py"},
        {"path": "myapp/urls.py"},
        {"path": "docs/urls.md"},
        {"path": "backup/urls.py.bak"},
    ]

    result = detect_django_urls(files)

    url_paths = [r["path"] for r in result if r.get("framework_kind") == "django_urls"]
    assert len(url_paths) == 2
    assert "urls.py" in url_paths
    assert "myapp/urls.py" in url_paths
    assert "docs/urls.md" not in url_paths
    assert "backup/urls.py.bak" not in url_paths


def test_detect_django_services_identifies_common_patterns():
    """Service modules (services.py, queries.py, etc.) indicate business logic."""
    files = [
        {"path": "myapp/services.py"},
        {"path": "myapp/queries.py"},
        {"path": "myapp/models.py"},
        {"path": "myapp/views.py"},
    ]

    result = detect_django_services(files)

    service_paths = [r["path"] for r in result if r.get("framework_kind") == "django_service"]
    assert len(service_paths) == 2
    assert "myapp/services.py" in service_paths
    assert "myapp/queries.py" in service_paths
    assert "myapp/models.py" not in service_paths
    assert "myapp/views.py" not in service_paths


def test_detect_django_services_recognizes_all_service_patterns():
    """Should detect services, queries, managers, and helpers."""
    files = [
        {"path": "myapp/services.py"},
        {"path": "myapp/queries.py"},
        {"path": "myapp/managers.py"},
        {"path": "utils/helpers.py"},
        {"path": "myapp/middleware.py"},
    ]

    result = detect_django_services(files)

    service_paths = [r["path"] for r in result if r.get("framework_kind") == "django_service"]
    assert len(service_paths) == 4
    assert "myapp/services.py" in service_paths
    assert "myapp/queries.py" in service_paths
    assert "myapp/managers.py" in service_paths
    assert "utils/helpers.py" in service_paths
    assert "myapp/middleware.py" not in service_paths


def test_detect_functions_handle_windows_paths():
    """Path detection should work with Windows backslash separators."""
    windows_files = [
        {"path": "myapp\\migrations\\0001_initial.py"},
        {"path": "myapp\\urls.py"},
        {"path": "myapp\\apps.py", "language": "python"},
        {"path": "myapp\\services.py"},
    ]

    migrations = detect_migrations(windows_files)
    urls = detect_django_urls(windows_files)
    apps = detect_django_apps(windows_files)
    services = detect_django_services(windows_files)

    assert len([r for r in migrations if r.get("framework_kind") == "django_migration"]) == 1
    assert len([r for r in urls if r.get("framework_kind") == "django_urls"]) == 1
    assert len([r for r in apps if r.get("framework_kind") == "django_app"]) == 1
    assert len([r for r in services if r.get("framework_kind") == "django_service"]) == 1
