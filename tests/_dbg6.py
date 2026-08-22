import httpx
from apiverity.mock import MockServer
from apiverity.specs.loader import detect_and_load

service, _, _ = detect_and_load("fixtures/apis/crud/openapi.yaml")
with MockServer(service, port=8093) as mock:
    try:
        r = httpx.post(mock.base_url + "/users", json={"name": "alice"})
        print("status:", r.status_code, "body:", r.text[:120])
    except Exception as exc:
        print("CLIENT ERROR:", type(exc).__name__, exc)