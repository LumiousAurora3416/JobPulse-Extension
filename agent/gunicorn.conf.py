"""Gunicorn config for the JobPulse callback / match service.

Auto-loaded: Render's start command is
    cd agent && gunicorn callback_server:app --bind 0.0.0.0:$PORT
Gunicorn reads ./gunicorn.conf.py from the working directory, so this file is
picked up without touching the Render dashboard. Command-line flags still win
over this file (e.g. --bind stays as-is).

Timeout budget (outermost wins the race, so inner must be smaller):
    LLM request 75s  <  gunicorn 90s  <  Cloudflare 100s  <  extension 95s

Why this matters: gunicorn's default timeout is 30s. The match engine's LLM call
can legitimately take longer than that, and when the worker is killed mid-request
the client receives a 500 with an EMPTY body -- which the extension can only
report as the useless "响应异常 HTTP 500". The handler's own try/except never
runs, because the process is killed from the outside.
"""

# Must stay above match_engine.LLM_REQUEST_TIMEOUT (75s). See budget above.
timeout = 90


def post_fork(server, worker):
    """Warm up inside the worker process before it starts serving.

    match_engine is imported lazily on the first request, and jieba builds its
    prefix dictionary on first use (~3.7s observed on Render). Doing both here
    moves that cost off the user's first call -- which is exactly the cold-start
    call that used to blow the timeout.

    Failures are swallowed on purpose: a broken match engine must never stop the
    callback service from booting.
    """
    try:
        from match_engine import warmup

        warmup()
        worker.log.info("match_engine warmed up (jieba dictionary built)")
    except Exception as e:  # noqa: BLE001 - startup warmup must never be fatal
        worker.log.warning("match_engine warmup skipped: %s", e)
