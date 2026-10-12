# Design decisions

One entry per decision: what was chosen, what else was considered, why, and what it costs.

## 1. Parse SQL into an AST (sqlglot) instead of matching text

- **Decision.** `check_sql` parses the model's output with sqlglot in the SQLite dialect and
  inspects the tree: one statement, a `SELECT` or set operation at the root, no write or
  schema nodes anywhere, allow-listed tables only, no denied functions.
- **Alternatives.** Check that the text starts with `SELECT`; a keyword deny-list with regex.
- **Why.** A prefix check passes `SELECT 1; DROP TABLE trips` and
  `WITH x AS (SELECT 1) DELETE FROM trips`. A keyword regex blocks harmless queries such as
  `WHERE zone = 'DROP TABLE trips'` and can be dodged with comments. The tree shows structure,
  so a keyword inside a string literal is just a string. Both cases are in `tests/unit/test_guard.py`.
- **Trade-off.** The guard is only as good as the parser. sqlglot does not model every SQLite
  statement (`VACUUM`, `EXPLAIN` and `REPLACE` come back as an opaque `Command` node), so anything
  it cannot parse or does not recognise is blocked. That can reject valid but unusual queries.

## 2. Defence in depth: the executor does not trust the guard

- **Decision.** Four independent layers: the AST guard, a read-only connection
  (`mode=ro` plus `PRAGMA query_only`), a `set_authorizer` callback that denies every action
  except read, select, function and recursive (and refuses reads of `sqlite_*` catalogue
  tables), and a timeout with a row cap.
- **Alternatives.** Rely on the guard alone; rely on a read-only file alone.
- **Why.** Each layer has a different failure mode. A parser bug could let a write through the
  guard; the authorizer still refuses it when SQLite compiles the statement. A read-only file
  does nothing about a query that never finishes; the timeout does. Tests send `DELETE`,
  `DROP`, `ATTACH` and `PRAGMA` straight to `execute()` with no guard and check the file hash.
- **Trade-off.** More code and some overlap. The authorizer's allow-list also rules out things
  that would be harmless, such as `PRAGMA table_info`.

## 3. SQLite opened read-only, one connection per request

- **Decision.** The data lives in one SQLite file, opened as `file:...?mode=ro` with `uri=True`.
  The API opens a fresh connection for each request.
- **Alternatives.** Postgres with a read-only role; DuckDB; a shared connection pool.
- **Why.** SQLite needs no server, so the project runs from a clean clone with no Docker, and
  the authorizer and progress-handler hooks are in the Python standard library. `mode=ro` also
  means a missing file is an error instead of a new empty database. A connection per request
  avoids sharing a `sqlite3` connection across threads; opening one costs well under a millisecond.
- **Trade-off.** No role-based permissions or row-level security, so multi-tenant isolation
  would need a different database. Date handling is SQLite-specific (`strftime`, `julianday`),
  which is where the model makes many of its mistakes.

## 4. A strict execution-accuracy comparator

- **Decision.** Run predicted and gold SQL through the same executor and compare the result
  sets: floats rounded to 2 decimals, strings stripped, rows compared as a multiset unless the
  question asks for an order. A different number of columns is a failure with its own label,
  `col_count_mismatch`.
- **Alternatives.** Exact match on SQL text; an LLM as judge; lenient matching that accepts
  extra columns or any column order.
- **Why.** Text match fails every correct query written differently from the gold one. An LLM
  judge adds a second unmeasured model to the measurement. Lenient matching hides real errors:
  a result with the right numbers in the wrong columns is not a right answer for someone
  reading the table.
- **Trade-off.** False negatives: a correct query that also returns the zone ID, or returns the
  hour as `'07'` instead of `7`, is marked wrong. False positives: two queries that both return
  nothing, or that agree by coincidence on this data, are marked right. The questions say which
  columns to return to keep the first kind down.

## 5. At most one repair attempt, and only for database errors

- **Decision.** Under S2, if the query fails in SQLite, the error and the failed SQL go back to
  the model once. A blocked query, a timeout or a reply with no SQL is never retried.
- **Alternatives.** No repair; retry until it runs; retry blocked queries too.
- **Why.** One retry fixes the cheap mistakes (a misspelt column, a function SQLite lacks).
  Each further retry doubles worst-case latency for little gain, and a model that cannot fix
  the query with the error in front of it rarely does on the third try. Retrying a blocked
  query would let the model iterate against the guard, which is the opposite of the point.
- **Trade-off.** Repair only helps queries that fail loudly. A query that runs and returns the
  wrong answer is never repaired, and those are the more dangerous errors.

## 6. A local model, pinned by tag

- **Decision.** The default provider is Ollama running `qwen2.5-coder:7b` at temperature 0 with
  a fixed seed. The tag and digest are written into every results file.
- **Alternatives.** A hosted frontier model through an API.
- **Why.** It costs nothing, the data and questions never leave the machine, and a pinned tag
  makes a run repeatable. A provider interface keeps the choice open: `OpenAICompatProvider`
  talks to any chat-completions endpoint, and a swap can be judged on the same eval set.
- **Trade-off.** Lower accuracy and much higher latency than a hosted model, especially on a
  laptop CPU. The numbers in the README describe this model on this hardware, not the approach
  in general.

## 7. Only reviewed questions count, with explicit provenance

- **Decision.** `make eval` scores only questions whose `verified_by` field is set.
  `verification_method` distinguishes automated review from human review. Reports preserve
  that distinction; automated review must never be attributed to a human. A run with
  `--include-unverified` is allowed, but the JSON records it and the report is headed DRAFT.
- **Alternatives.** Score every question that has gold SQL that runs.
- **Why.** Gold SQL that runs is not the same as gold SQL that answers the question. If the
  gold is wrong, a correct prediction is scored as a failure and the accuracy figure means
  nothing. `make verify-gold` prints each question with its SQL and result to make the check quick.
- **Trade-off.** The evaluated set is smaller than the written one until every question is checked.

## 8. Few-shot examples are fixed and kept apart from the eval set

- **Decision.** S2 uses three fixed examples (a join, a time question, a group-by) stored in
  `eval/fewshot.jsonl`. A test fails if any of them matches an eval question by normalised
  text or by normalised SQL.
- **Alternatives.** Pick examples per question by similarity; draw examples from the eval set.
- **Why.** If an eval question appears in the prompt with its answer, the model can copy it
  and accuracy is inflated. Fixed examples also keep the prompt prefix identical across
  questions, so a local model reuses its cached prefix.
- **Trade-off.** Three static examples cannot cover every query shape; window functions, for
  instance, have no example.

## 9. A larger page cache on the read-only connection

- **Decision.** `open_readonly` sets `PRAGMA cache_size` to 64 MB.
- **Alternatives.** Leave the 2 MB default; add covering indexes; raise the timeout.
- **Why.** With the default cache, a `GROUP BY` that walks an index took 2 to 2.7 s on the
  250,000-row table, close enough to the 3 s timeout that correct queries could be cut off.
  With 64 MB the same queries take 0.5 to 1 s. Raising the timeout would have weakened a
  guardrail to hide a tuning problem.
- **Trade-off.** Up to 64 MB of memory per open connection, which is fine for one user and
  would need a pool with a shared cache under real load.
