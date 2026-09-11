# apiverity-house-rules

A worked example of an [api-verity-lab](https://github.com/webdevsamran/api-verity-lab)
rule pack, shipped as its own package.

```bash
pip install -e examples/plugins/apiverity-house-rules
apiverity rules --packs            # house-rules is listed, with its source
apiverity validate openapi.yaml    # HOUSE-* findings appear alongside the built-ins
```

Three rules a platform team would want and the engine deliberately does not
ship, because they are house style rather than facts about contracts:

| Rule | |
|---|---|
| `HOUSE-PATH-CASE` | Path segments are kebab-case. |
| `HOUSE-LIST-PAGINATION` | A collection `GET` declares a paging parameter. |
| `HOUSE-ERROR-SHAPE` | Every operation declares at least one 4xx response. |

That is the line the plugin system draws: the engine ships rules about what
**breaks consumers**, and a pack ships rules about what a **team has agreed
to**. "Paths are kebab-case" is true for many teams and false for the ones who
standardised on something else years ago — as a built-in it would be a false
positive on their first run, and a false positive is what gets a rule switched
off along with its neighbours.

[`docs/plugin-authoring.md`](https://github.com/webdevsamran/api-verity-lab/blob/main/docs/plugin-authoring.md)
is the guide this package is the worked example for.
