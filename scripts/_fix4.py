import pathlib
NL = chr(10)
p = pathlib.Path("apiverity/cli/main.py")
t = p.read_text(encoding="utf-8")
t = t.replace('        print("' + NL + '".join(lines))', '        print(NL.join(lines))')
t = t.replace('    (out / "SHA256SUMS").write_text(' + NL +
              '        "' + NL + '".join(f"{v}  {k}" for k, v in checksums.items()) + "' + NL +
              '", encoding="utf-8")',
              '    (out / "SHA256SUMS").write_text(' + NL +
              '        NL.join(f"{v}  {k}" for k, v in checksums.items()) + NL, encoding="utf-8")')
if "NL = chr(10)" not in t:
    t = t.replace("EXIT_OK = 0", "NL = chr(10)" + NL + NL + "EXIT_OK = 0")
p.write_text(t, encoding="utf-8")
print("fixed:", '"' + NL + '"' not in t)