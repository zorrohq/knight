## Status

- [ ] 1. select() fragile with text=True pipes
- [x] 2. agent_end final_message extraction dead code — fixed in 5af333c
- [ ] 3. Session data grows unbounded in DB
- [x] 4. No set_auto_retry — fixed in 5af333c
- [ ] 5. Upsert race condition in session_store / config_store
- [ ] 6. langchain heavy dependency — kept intentionally
- [x] 7. GitHub API calls have no retry — fixed in 9afd8b3
- [x] 8. Webhook signature timing attack — already using hmac.compare_digest correctly
- [x] 9. No Celery task timeout — fixed in c3b798b (soft 140min / hard 150min + acks_late)
- [ ] 10. pi_provider_map.json only maps google-genai
- [x] 11. No DLQ for failed tasks — partially fixed (acks_late + reject_on_worker_lost in c3b798b)
- [ ] 12. Commit message and PR description use separate LLM calls
- [ ] 13. No rate limiting on webhook endpoint
- [x] 14. experimental/ and references/ in Docker image — fixed in 316a590
- [ ] 15. Worktree cleanup is best-effort
- [x] 16. No error reporting back to GitHub — fixed in bfc132e

---

## Critical / Bugs

**1. select() won't work with text=True pipes on Python 3.13**

In service.py:264, `select.select([proc.stdout], ...)` takes a file-like object from `Popen(text=True)`. On Linux this works because `TextIOWrapper` exposes `.fileno()`, but it's fragile — `readline()` after `select` can still block if a partial line is buffered in the TextIOWrapper layer (select sees raw fd ready, but `readline` waits for `\n` in the Python buffer).

Fix: Use `bufsize=0` and `text=False` (raw bytes), or better — move the switch_session wait into the reader thread instead of doing it on the main thread.

**2. ~~agent_end final_message extraction is wrong~~ — fixed 5af333c**

**3. Session data grows unbounded in the DB**

`session_data` is a `Text` column storing full JSONL. After many iterations on a long issue, this can be megabytes. No size limit, no compaction trigger, no TTL cleanup.

Fix: Add a max size check before save. If over threshold, compact (or rely on pi's auto_compaction already having trimmed). Add a periodic cleanup job for stale sessions (e.g. issues closed > 7 days).

**4. ~~No set_auto_retry in RPC init~~ — fixed 5af333c**

---

## Medium / Correctness

**5. Upsert race condition in session_store.py and config_store.py**

The pattern is: `INSERT → IntegrityError → rollback → UPDATE`. Under concurrent writes (two triggers for the same issue), both can INSERT simultaneously, one fails, both UPDATE — last write wins with no merge. Data loss is possible (newer session overwrites a richer one).

Fix: Use database-level `ON CONFLICT ... DO UPDATE` (Postgres) or equivalent, in a single statement.

**6. langchain is a heavy unused dependency — kept intentionally**

**7. ~~GitHub API calls have no retry logic~~ — fixed 9afd8b3**

**8. ~~Webhook secret validation timing attack~~ — already correct**

**9. ~~Worker has no task timeout at Celery level~~ — fixed c3b798b**

**10. pi_provider_map.json only maps google-genai**

`{"google-genai": "google"}`

If Anthropic or other providers need mapping in the future, this silently passes through the unmapped name. Not a bug today, but brittle.

**11. No dead letter queue for failed tasks — partially fixed c3b798b**

`acks_late=True` and `reject_on_worker_lost=True` added. Still missing: explicit DLQ routing and retry policy config.

**12. Commit message and PR description use separate LLM calls**

`commit_message.py` and `pr_description.py` each make an independent LLM call for the same diff. Could be combined into one call returning both.

**13. No rate limiting on webhook endpoint**

A malicious actor (or GitHub retry storm) can flood the webhook endpoint and fill the Celery queue. The API has no rate limiting or deduplication.

---

## Low / Improvements

**14. ~~experimental/ and references/ shipped in Docker image~~ — fixed 316a590**

**15. Worktree cleanup is best-effort**

`shutil.rmtree(worktree_path, ignore_errors=True)` in git_ops.py can leave orphaned worktrees if the path has locked files. Over time this fills disk.

Fix: Add a periodic cleanup sweep in the worker for stale worktree directories.

**16. ~~No structured error reporting back to GitHub~~ — fixed bfc132e**
