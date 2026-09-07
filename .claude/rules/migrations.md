# Rule: migrations

Every schema change is an Alembic migration in io_assistant/db/migrations/versions/.
No ad-hoc ALTER. The embedding dimension is fixed (config.embedding_dim); changing
it or the embedding model requires a migration plus a backfill of every embedding
column.
