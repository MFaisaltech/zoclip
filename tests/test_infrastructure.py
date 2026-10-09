import os
import subprocess
import sys
from uuid import uuid4

import pytest
from redis import Redis
from rq import Queue


@pytest.mark.integration
def test_real_redis_rq_roundtrip():
    url = os.environ.get("TEST_REDIS_URL", "")
    if not url:
        pytest.skip("TEST_REDIS_URL required for real Redis/RQ worker smoke")
    if not url.endswith("/15"):
        pytest.fail("Use disposable Redis database 15")
    connection = Redis.from_url(url)
    queue = Queue(f"phase1-test-{uuid4()}", connection=connection)
    job = queue.enqueue(os.getpid, result_ttl=60, job_timeout=20)
    # A distinct worker process consumes the job. SimpleWorker is portable to
    # Windows; the separate Compose smoke verifies the actual Linux Worker entrypoint.
    worker_code = (
        "import os; from redis import Redis; from rq import Queue, SimpleWorker; "
        "r=Redis.from_url(os.environ['TEST_REDIS_URL']); "
        "q=Queue(os.environ['PHASE1_SMOKE_QUEUE'], connection=r); "
        "SimpleWorker([q], connection=r).work(burst=True, with_scheduler=False)"
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-c", worker_code],
            env=os.environ | {"PHASE1_SMOKE_QUEUE": queue.name},
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        job.refresh()
        assert job.is_finished
        worker_pid = job.return_value(refresh=True)
        assert isinstance(worker_pid, int) and worker_pid > 0 and worker_pid != os.getpid()
    finally:
        job.delete()
        queue.delete()
        connection.close()
