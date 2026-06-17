# SQLite Persistence

The runtime supports a transactional SQLite persistence baseline for sessions
and workflow cases. It replaces full-file JSON rewrites with database
transactions, schema migrations, indexed case queries, and WAL-based concurrent
access.

## Enable

```bash
export AI_RISK_SESSION_STORE_BACKEND=sqlite
export AI_RISK_CASE_STORE_BACKEND=sqlite
export AI_RISK_DATABASE_PATH=.data/platform.db
```

Both stores should use the same database path. The application initializes and
records schema migrations automatically at startup.

## Guarantees

- Session turn appends and case status updates use immediate transactions.
- Concurrent writers are serialized instead of overwriting each other.
- Case creation is idempotent for each session turn and protected by a unique
  database constraint.
- Case filters, sorting, counts, and pagination execute through indexed SQL.
- `GET /admin/runtime` exposes the active database path and checks database
  connectivity in readiness.

SQLite is the local and single-instance database baseline.

## PostgreSQL For Shared Deployments

Use PostgreSQL before horizontal scaling:

```bash
export AI_RISK_SESSION_STORE_BACKEND=postgres
export AI_RISK_CASE_STORE_BACKEND=postgres
export AI_RISK_POSTGRES_DSN_FILE=/run/secrets/ai-risk-postgres-dsn
```

The application uses the same session and case contracts, creates the required
tables and indexes through schema migrations, and exposes PostgreSQL readiness
without returning the DSN. Install the optional `psycopg` driver in the
deployment image before enabling the `postgres` backends.
