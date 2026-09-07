from io_assistant.backend.factory import build_backend
from io_assistant.backend.local import LocalBackend
from io_assistant.backend.hybrid import HybridBackend


def test_local(config):
    assert isinstance(build_backend(config), LocalBackend)


def test_hybrid(config):
    config.backend.provider = "hybrid"
    b = build_backend(config)
    assert isinstance(b, HybridBackend)


def test_hybrid_routes_split(config):
    class L:
        def route(self, u): return "store"
        def extract(self, *a): return "LOCAL"
        def plan(self, *a): ...
        def phrase(self, *a): ...

    class C:
        def route(self, u): return "query"
        def extract(self, *a): return "CLOUD"
        def plan(self, *a): ...
        def phrase(self, *a): ...

    from io_assistant.backend.hybrid import HybridBackend
    h = HybridBackend(L(), C())
    assert h.route("x") == "store"
    assert h.extract("x", None) == "CLOUD"
