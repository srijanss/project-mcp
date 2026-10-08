from project_mcp.plugins.react.routes import route_declarations


def test_route_elements_declare_a_path_and_the_component_they_render():
    source = (
        "<Routes>\n"
        '  <Route path="/users" element={<Users />} />\n'
        "  <Route element={<Layout />} path='/about' />\n"
        "  <Route\n"
        "    path={'/blog'}\n"
        "    element={<Blog posts={posts} onOpen={() => open()} />}\n"
        "  />\n"
        "</Routes>\n"
    )

    assert route_declarations(source) == [
        ("/users", "Users", 2),
        ("/about", "Layout", 3),
        ("/blog", "Blog", 4),
    ]


def test_route_elements_without_a_path_or_a_component_element_are_skipped():
    source = (
        "<Route index element={<Home />} />\n"
        '<Route path="/x" element={<div />} />\n'
        '<Route path="/y" element={renderY()} />\n'
        '<Route path="/z" />\n'
    )

    assert route_declarations(source) == []


def test_router_config_objects_declare_paths_in_either_key_order():
    source = (
        "export const router = createBrowserRouter([\n"
        "  { path: '/', element: <Home /> },\n"
        '  { element: <About title="a" />, path: "/about" },\n'
        "]);\n"
    )

    assert route_declarations(source) == [("/", "Home", 2), ("/about", "About", 3)]


def test_config_objects_only_count_in_files_that_create_a_router():
    source = "const menu = [{ path: '/', element: <Home /> }];\n"

    assert route_declarations(source) == []


def test_commented_out_routes_are_ignored():
    source = (
        '// <Route path="/old" element={<Old />} />\n'
        '/* <Route path="/older" element={<Older />} /> */\n'
        '<Route path="/new" element={<New />} />\n'
    )

    assert route_declarations(source) == [("/new", "New", 3)]


def test_config_objects_may_have_other_keys_between_path_and_element():
    source = (
        "export const router = createBrowserRouter([\n"
        "  { path: '/users', loader: loadUsers, element: <Users /> },\n"
        "  { element: <Shell />, errorElement: <Oops />, path: '/shell' },\n"
        "]);\n"
    )

    assert route_declarations(source) == [("/users", "Users", 2), ("/shell", "Shell", 3)]


def test_a_route_object_without_a_path_does_not_borrow_its_children_paths():
    source = (
        "export const router = createBrowserRouter([\n"
        "  {\n"
        "    element: <Layout />,\n"
        "    children: [{ path: 'a', element: <A /> }],\n"
        "  },\n"
        "]);\n"
    )

    assert route_declarations(source) == [("a", "A", 4)]
