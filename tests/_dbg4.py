import tests._smoke3 as s
from apiverity.rules.breaking import evaluate_breaking

old = s.load(s.V1)
new = s.load(s.V2)
changes = s.diff_services(old, new)
enum_changes = [c for c in changes if c.kind.value == "enum_changed"]
for c in enum_changes:
    print("dir:", repr(c.direction), "old:", c.old_value, "new:", c.new_value)
findings = evaluate_breaking(enum_changes)
for f in findings:
    print(f.rule_id, "|", f.message[:80])