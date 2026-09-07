# Rule: test discipline

TDD: failing test first, watch it fail, minimal implementation, watch it pass,
commit. Never mock the database — tests run against the real PostgreSQL named by
IO_TEST_DATABASE_URL. Backend model calls may be faked via the FakeBackend test
double; the persistence, resolver, and SQL layers never are.
