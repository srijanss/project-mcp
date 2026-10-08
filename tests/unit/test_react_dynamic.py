from project_mcp.plugins.react.dynamic import computed_components, dynamic_route_lines, lazy_imports


def test_lazy_imports_map_the_local_name_to_the_dynamically_imported_module():
    source = (
        "const A = React.lazy(() => import('./A'));\n"
        'export const B = lazy(() => import("./B"));\n'
        "const C = lazy(async () => {\n  return import('./C');\n});\n"
        "const plain = () => import('./plain');\n"
        "// const D = lazy(() => import('./D'));\n"
    )

    assert lazy_imports(source) == {"A": "./A", "B": "./B"}


def test_computed_components_list_the_candidates_of_a_conditional_choice():
    source = (
        "const One = flag ? Alpha : Beta;\n"
        "const Two = a ? First : b ? Second : Third;\n"
        "const three = flag ? Alpha : Beta;\n"
        "const Four = flag ? 'x' : Alpha;\n"
        "const Five = Alpha;\n"
    )

    assert computed_components(source) == {
        "One": ["Alpha", "Beta"],
        "Two": ["First", "Second", "Third"],
    }


def test_dynamic_route_lines_flag_spread_and_non_literal_route_configs():
    source = (
        '<Route path="/ok" element={<Ok />} />\n'
        "<Route {...routeProps} />\n"
        "<Route\n"
        "  path={computed}\n"
        "  element={<X />}\n"
        "/>\n"
        "<Route path={'/lit'} element={<Y />} />\n"
    )

    assert dynamic_route_lines(source) == [2, 3]


def test_spread_entries_in_router_config_arrays_are_dynamic():
    source = (
        "export const router = createBrowserRouter([\n"
        "  { path: '/', element: <Home /> },\n"
        "  ...extraRoutes,\n"
        "]);\n"
    )

    assert dynamic_route_lines(source) == [3]


def test_spreads_outside_router_files_are_not_dynamic_routes():
    assert dynamic_route_lines("const all = [...a, ...b];\n") == []
