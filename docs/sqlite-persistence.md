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

SQLite is the local and single-instance database baseline. A multi-instance
production deployment should implement the same store contracts on PostgreSQL
before horizontal scaling.
