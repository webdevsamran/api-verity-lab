"""One-off repairs: parser.py label line + Parameter.schema rename."""
import pathlib

NL = chr(10)

# --- fix 1: openapi parser label line ---
p = pathlib.Path("apiverity/specs/openapi/parser.py")
t = p.read_text(encoding="utf-8")
old = (
    '    label = source if source.startswith("http") else '
    'source.replace(chr(92), chr(47))' + '").split("/")[-1]'
)
assert old in t, "parser old not found"
new = (
    "    from pathlib import Path as _Path" + NL
    + NL
    + '    label = source if source.startswith("http") else _Path(source).name'
)
t = t.replace(old, new)
p.write_text(t, encoding="utf-8")
print("parser fixed")

# --- fix 2: rename Parameter.schema -> schema_node ---
m = pathlib.Path("apiverity/core/model.py")
mt = m.read_text(encoding="utf-8")
old2 = "    schema: Optional[SchemaNode] = None"
assert old2 in mt, "model old not found"
new2 = "    schema_node: Optional[SchemaNode] = None"
mt = mt.replace(old2, new2)
m.write_text(mt, encoding="utf-8")

pp = pathlib.Path("apiverity/specs/openapi/parser.py")
pt = pp.read_text(encoding="utf-8")
pt = pt.replace("            schema=schema,", "            schema_node=schema,")
pp.write_text(pt, encoding="utf-8")
print("model fixed")