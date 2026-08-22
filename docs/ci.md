# CI Integration

## Blocking breaking changes on PRs

```yaml
name: api-verity
on:
  pull_request:
    paths: ["**/openapi*.yaml", "**/openapi*.json"]
permissions:
  contents: read
jobs:
  contract:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e .
      - name: Validate PR contract
        run: apiverity validate api/openapi.yaml
      - name: Diff vs base
        run: |
          git fetch origin ${{ github.base_ref }}
          apiverity diff <(git show origin/${{ github.base_ref }}:api/openapi.yaml) api/openapi.yaml --json > diff.json
      - name: Breaking gate
        run: apiverity breaking <(git show origin/${{ github.base_ref }}:api/openapi.yaml) api/openapi.yaml --check-semver
```

Exit code `1` fails the job when ERROR-severity findings exist — that is the
release gate. Use `--severity-override` to tune strictness per repo.

## Artifacts
- `apiverity report <bundle> --format junit` → JUnit test reporting.
- `apiverity report <bundle> --format sarif` → upload with
  `github/codeql-action/upload-sarif` or `actions/upload-artifact`.
- `apiverity report <bundle> --format markdown` → paste into the PR summary
  (keep it to one comment; update it on push instead of adding new ones).

## Performance gates
```yaml
- run: apiverity baseline api/openapi.yaml --base-url $STAGING -o baseline.json
- run: apiverity regression api/openapi.yaml --base-url $STAGING --baseline baseline.json --policy "GET /users p95 <= 250ms"
```
