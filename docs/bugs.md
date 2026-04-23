Critical / Bugs

  1. select() won't work with text=True pipes on Python 3.13

  In service.py:264, select.select([proc.stdout], ...) takes a file-like object from Popen(text=True). On Linux this works because
  TextIOWrapper exposes .fileno(), but it's fragile — readline() after select can still block if a partial line is buffered in the
  TextIOWrapper layer (select sees raw fd ready, but readline waits for \n in the Python buffer).

  Fix: Use bufsize=0 and text=False (raw bytes), or better — move the switch_session wait into the reader thread instead of doing it on the
   main thread.

  2. agent_end final_message extraction is wrong

  # service.py:438-442
  elif event_type == "agent_end":
      agent_end_event = event
      final_message = (
          event.get("message")        # ← agent_end has "messages" (array), not "message"
          or event.get("final_message")  # ← doesn't exist in pi RPC
          or final_message
      )

  From the RPC docs, agent_end has {"type": "agent_end", "messages": [...]}. Neither message nor final_message exists. This always falls
  through to the already-set final_message from message_end, which works by accident. Should be cleaned up or removed.

  3. Session data grows unbounded in the DB

  session_data is a Text column storing full JSONL. After many iterations on a long issue, this can be megabytes. No size limit, no
  compaction trigger, no TTL cleanup.

  Fix: Add a max size check before save. If over threshold, compact (or rely on pi's auto_compaction already having trimmed). Add a
  periodic cleanup job for stale sessions (e.g. issues closed > 7 days).

  4. No set_auto_retry in RPC init

  Pi supports set_auto_retry for transient LLM errors (rate limits, 5xx, overloaded). We don't enable it. A single 429/529 kills the entire
   run.

  Fix:
  proc.stdin.write(json.dumps({"type": "set_auto_retry", "enabled": True}) + "\n")

  ---
  Medium / Correctness

  5. Upsert race condition in session_store.py and config_store.py

  The pattern is: INSERT → IntegrityError → rollback → UPDATE. Under concurrent writes (two triggers for the same issue), both can INSERT
  simultaneously, one fails, both UPDATE — last write wins with no merge. Data loss is possible (newer session overwrites a richer one).

  Fix: Use database-level ON CONFLICT ... DO UPDATE (Postgres) or equivalent, in a single statement.

  6. langchain is a heavy unused dependency

  It's only used in commit_message.py and pr_description.py for init_chat_model(). The actual coding agent uses pi directly. langchain +
  langchain-openai + langchain-anthropic + langchain-google-genai pulls in hundreds of transitive deps, bloats the Docker image, and
  creates version conflict risk.

  Fix: Replace with direct openai/anthropic SDK calls (you already have httpx). Two small functions, no framework needed.

  7. GitHub API calls have no retry logic

  knight/runtime/github.py functions (create_github_pr, post_issue_comment, react_to_comment) do a single requests.post() with no retry.
  GitHub returns 502/503 regularly under load. A failed PR creation or comment post silently fails the post-workflow.

  Fix: Add urllib3.util.Retry with requests.adapters.HTTPAdapter, or use httpx with tenacity.

  8. Webhook secret validation timing attack

  In github.py, if you're comparing signatures with == instead of hmac.compare_digest(), it's vulnerable to timing attacks. Need to verify
  the actual implementation.

  9. Worker has no task timeout at Celery level

  The Celery task run_agent_task has no time_limit or soft_time_limit. If the agent hangs AND the thread timeout fails (e.g. select bug
  above), the worker slot is consumed forever.

  Fix: Add @celery_app.task(soft_time_limit=7800, time_limit=8000) (slightly above the pi timeout).

  10. pi_provider_map.json only maps google-genai

  {"google-genai": "google"}

  If Anthropic or other providers need mapping in the future, this silently passes through the unmapped name. Not a bug today, but brittle.

  ---
  Low / Improvements

  11. No dead letter queue for failed tasks

  Failed Celery tasks disappear. No retry, no DLQ, no alerting. If pi crashes, the issue gets no response.

  Fix: Configure task_acks_late=True, task_reject_on_worker_lost=True, and a DLQ/retry policy.

  12. Commit message and PR description use separate LLM calls

  commit_message.py and pr_description.py each make an independent LLM call for the same diff. Could be combined into one call returning
  both.

  13. No rate limiting on webhook endpoint

  A malicious actor (or GitHub retry storm) can flood the webhook endpoint and fill the Celery queue. The API has no rate limiting or
  deduplication.

  14. experimental/ and references/ shipped in Docker image

  The Dockerfile copies the entire project. These directories add bloat for no runtime value.

  Fix: Add .dockerignore excluding experimental/, references/, docs/, .git/.

  15. Worktree cleanup is best-effort

  shutil.rmtree(worktree_path, ignore_errors=True) in git_ops.py can leave orphaned worktrees if the path has locked files. Over time this
  fills disk.

  Fix: Add a periodic cleanup sweep in the worker for stale worktree directories.

  16. No structured error reporting back to GitHub

  If the agent fails (provider error, timeout, crash), the issue gets no comment. The user is left wondering. Only success (PR created)
  posts a notification.

  Fix: In the task's exception handler, post an issue comment like "I ran into an error processing this. Details: ..."

  ---
  Quick wins I'd prioritize

  1. Add set_auto_retry (one line, prevents wasted runs)
  2. Fix agent_end message extraction (dead code cleanup)
  3. Add Celery time_limit (prevents zombie workers)
  4. Add failure comments on GitHub (user experience)
  5. Replace langchain with direct SDK calls (image size, simplicity)

  Want me to implement any of these?
