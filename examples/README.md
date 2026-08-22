# Examples

All examples run fully locally against bundled fixtures.

## 60-second tour

```bash
pip install -e .

# 1. validate a contract
apiverity validate fixtures/apis/crud/openapi.yaml

# 2. diff two versions and gate on breaking changes + semver
apiverity breaking fixtures/apis/versioned/v1.yaml \
                fixtures/apis/versioned/v2.yaml --check-semver

# 3. generate a changelog
apiverity changelog fixtures/apis/versioned/v1.yaml \
                    fixtures/apis/versioned/v2.yaml -o CHANGELOG-draft.md

# 4. mock, test, workflow, drift, performance against the mock
python - <<'PY'
from apiverity.specs.loader import detect_and_load
from apiverity.mock import MockServer
service, _, _ = detect_and_load("fixtures/apis/crud/openapi.yaml")
with MockServer(service, port=8090) as m:
    print(m.base_url)   # then: apiverity test ... / workflow ... / drift ...
    import time; time.sleep(30)
PY

# 5. serve results + frontend bundle
apiverity serve web/dist --port 8080
```

See `fixtures/apis/` for the example contracts and
`fixtures/workflows/` for an authored lifecycle manifest.