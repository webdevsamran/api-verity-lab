import tests._smoke3 as s

old = s.load(s.V1)
new = s.load(s.V2)
changes = s.diff_services(old, new)
for c in changes:
    if c.kind.value == "enum_changed":
        print(c.id, "|", c.direction, "|", c.operation_key, "|", c.description)
print("total:", len(changes))