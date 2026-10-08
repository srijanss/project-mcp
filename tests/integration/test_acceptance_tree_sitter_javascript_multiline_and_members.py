from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan

SOURCE = """\
export function total(
  a: number,
  b: number,
): number {
  function double(x: number) {
    return x * 2;
  }
  return double(a) + b;
}

export class Store {
  static create() {
    return new Store();
  }

  async load() {}

  get size() {
    return 0;
  }
}

export interface Props {
  label: string;
}

export enum Color {
  Red,
}

export type Id = string;
"""


def test_tree_sitter_finds_symbols_the_regex_parser_misses_with_their_spans(tmp_path):
    (tmp_path / "store.ts").write_text(SOURCE)
    conn = get_connection(tmp_path)

    run_scan(conn, tmp_path, load_config(tmp_path))

    rows = conn.execute(
        "SELECT qualified_name, kind, start_line, end_line FROM symbols WHERE kind != 'module'"
    ).fetchall()
    assert sorted(rows) == [
        ("store.Color", "enum", 27, 29),
        ("store.Id", "type_alias", 31, 31),
        ("store.Props", "interface", 23, 25),
        ("store.Store", "class", 11, 21),
        ("store.Store.create", "method", 12, 14),
        ("store.Store.load", "method", 16, 16),
        ("store.Store.size", "method", 18, 20),
        ("store.total", "function", 1, 9),
        ("store.total.double", "function", 5, 7),
    ]
