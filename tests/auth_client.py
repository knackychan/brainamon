"""First-party test transport; negative authentication tests use FastAPI's raw client."""
from fastapi.testclient import TestClient as RawTestClient


class TestClient(RawTestClient):
    __test__ = False

    def __init__(self, app, *args, **kwargs):
        headers = dict(kwargs.pop('headers', {}) or {})
        headers.setdefault('Authorization', 'Bearer ' + app.state.api_token)
        super().__init__(app, *args, headers=headers, **kwargs)
