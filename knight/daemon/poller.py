"""Cloud job poller.

Runs as a background thread inside the API process. Polls knight.zorro.works for
pending jobs and feeds them into the local Celery queue via enqueue_agent_task().

Activated when config.json contains both `cloud_url` and `daemon_token`.
If either is absent, the poller is a no-op and direct-webhook mode continues
to work unchanged via the /api/github/webhook route.
"""
from __future__ import annotations

import logging
import threading
import time

import httpx

from knight.utils.local.config_store import ConfigStore
from knight.worker.producer import enqueue_agent_task

logger = logging.getLogger(__name__)

# Seconds between polls when no job was returned (backs off gradually up to this)
_POLL_INTERVAL_IDLE_MAX = 300
_POLL_INTERVAL_IDLE_MIN = 30
_POLL_INTERVAL_BUSY = 5  # immediately re-poll after receiving a job

# Heartbeat cadence — tells cloud this machine is alive
_HEARTBEAT_INTERVAL_BOOT   = 30   # first 3 minutes after startup
_HEARTBEAT_BOOT_WINDOW     = 180  # seconds to stay in boot cadence
_HEARTBEAT_INTERVAL_ACTIVE = 60   # jobs running (lease renewal)
_HEARTBEAT_INTERVAL_IDLE   = 180  # no jobs (just lastSeenAt)


class CloudPoller:
    """Polls knight.zorro.works for pending jobs and enqueues them into Celery.

    Usage::

        poller = CloudPoller()
        poller.start()   # no-op if daemon_token not configured
        ...
        poller.stop()
    """

    def __init__(self) -> None:
        cfg = ConfigStore()
        self._cloud_url: str = cfg.get_string(key="cloud_url", default="https://knight.zorro.works")
        self._token: str = cfg.get_string(key="daemon_token")
        self._machine_name: str = cfg.get_string(key="machine_name", default="")
        self._stop_event = threading.Event()
        self._active_jobs: set[str] = set()
        self._lock = threading.Lock()

        self._client: httpx.Client | None = None
        if self._token:
            self._client = httpx.Client(
                base_url=self._cloud_url,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=15,
            )

    def start(self) -> None:
        if not self._token:
            logger.info("daemon_token not set in config.json; cloud polling disabled")
            return
        poll_thread = threading.Thread(target=self._poll_loop, daemon=True, name="cloud-poller")
        hb_thread = threading.Thread(target=self._heartbeat_loop, daemon=True, name="cloud-heartbeat")
        poll_thread.start()
        hb_thread.start()
        logger.info("cloud poller started (cloud_url=%s)", self._cloud_url)

    def stop(self) -> None:
        self._stop_event.set()
        if self._client:
            self._client.close()

    # ------------------------------------------------------------------
    # Internal loops
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        idle_streak = 0
        while not self._stop_event.is_set():
            try:
                job = self._claim_next_job()
                if job:
                    idle_streak = 0
                    self._dispatch(job)
                    self._stop_event.wait(_POLL_INTERVAL_BUSY)
                else:
                    idle_streak += 1
                    interval = min(
                        _POLL_INTERVAL_IDLE_MIN * idle_streak,
                        _POLL_INTERVAL_IDLE_MAX,
                    )
                    self._stop_event.wait(interval)
            except Exception:
                logger.exception("cloud poll error; will retry")
                self._stop_event.wait(_POLL_INTERVAL_IDLE_MAX)

    def _heartbeat_loop(self) -> None:
        started_at = time.monotonic()
        active: list[str] = []  # safe default for first iteration
        while not self._stop_event.is_set():
            try:
                with self._lock:
                    active = list(self._active_jobs)
                assert self._client is not None
                self._client.post(
                    "/api/knight/daemon/heartbeat",
                    json={"active_jobs": active, "daemon_version": "0.1.0"},
                )
            except Exception:
                logger.debug("heartbeat failed; will retry", exc_info=True)

            # Re-read active jobs for interval decision so a job dispatched
            # during the HTTP call is reflected immediately
            with self._lock:
                has_active = bool(self._active_jobs)

            if time.monotonic() - started_at < _HEARTBEAT_BOOT_WINDOW:
                interval = _HEARTBEAT_INTERVAL_BOOT
            elif has_active:
                interval = _HEARTBEAT_INTERVAL_ACTIVE
            else:
                interval = _HEARTBEAT_INTERVAL_IDLE
            self._stop_event.wait(interval)

    # ------------------------------------------------------------------
    # Job lifecycle
    # ------------------------------------------------------------------

    def _claim_next_job(self) -> dict | None:
        assert self._client is not None
        resp = self._client.get("/api/knight/daemon/jobs/next")
        resp.raise_for_status()
        return resp.json().get("job")

    def _dispatch(self, job: dict) -> None:
        job_id: str = job["job_id"]
        with self._lock:
            self._active_jobs.add(job_id)
        try:
            payload = self._adapt(job)
            task_id = enqueue_agent_task(payload)
            logger.info(
                "cloud job enqueued",
                extra={"job_id": job_id, "celery_task_id": task_id, "issue_id": job.get("issue_id")},
            )
        except Exception:
            logger.exception("failed to enqueue cloud job", extra={"job_id": job_id})
            self._post_result(job_id, status="failed", final_message="Failed to enqueue task")
            with self._lock:
                self._active_jobs.discard(job_id)
            raise

    def _post_result(self, job_id: str, *, status: str, final_message: str = "") -> None:
        try:
            assert self._client is not None
            self._client.post(
                f"/api/knight/daemon/jobs/{job_id}/result",
                json={"status": status, "result_status": "error", "final_message": final_message},
            )
        except Exception:
            logger.debug("failed to post result for job %s", job_id, exc_info=True)

    def mark_job_done(self, job_id: str) -> None:
        """Called by worker tasks after completion to remove from active set."""
        with self._lock:
            self._active_jobs.discard(job_id)

    @staticmethod
    def _adapt(job: dict) -> dict:
        """Map cloud job payload to enqueue_agent_task payload."""
        return {
            "repository_url": job["repository_url"],
            "github_token": job["installation_token"],  # short-lived, generated by cloud
            "issue_id": job["issue_id"],
            "instructions": job["instructions"],
            "issue_context": job.get("issue_context", ""),
            "author_name": job.get("author_name", ""),
            "trigger_comment_id": job.get("trigger_comment_id"),
            "task_type": job.get("event_type", "issue"),
            "base_branch": job.get("base_branch", "main"),
            # Passed through so worker can POST result back to cloud
            "cloud_job_id": job["job_id"],
        }
