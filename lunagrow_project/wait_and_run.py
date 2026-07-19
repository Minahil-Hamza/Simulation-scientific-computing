#!/usr/bin/env python3
"""
Wait for the BioSim REST API to answer, then hand off to run.py's CLI.

Docker Compose's `depends_on` only waits for the container to *start*, not
for the Java process inside it to finish booting Maven/Spring and bind
port 8009. This polls the real endpoint (runbook 1: "Confirm it's up —
curl http://localhost:8009/api/simulation") before running any scenario,
so we don't race a cold server and misreport a connection failure as a
BioSim bug.
"""
import sys
import time
import requests

DEFAULT_URL = "http://biosim-server:8009/api/simulation"
MAX_WAIT_SECONDS = 120
POLL_INTERVAL_SECONDS = 2


def wait_for_server(url: str, max_wait: int = MAX_WAIT_SECONDS) -> None:
    deadline = time.time() + max_wait
    last_error = None
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=3)
            if r.status_code == 200:
                print(f"BioSim server is up at {url}")
                return
            last_error = f"HTTP {r.status_code}"
        except requests.exceptions.RequestException as exc:
            last_error = str(exc)
        time.sleep(POLL_INTERVAL_SECONDS)
    sys.exit(
        f"ERROR: BioSim server never became reachable at {url} "
        f"within {max_wait}s. Last error: {last_error}"
    )


if __name__ == "__main__":
    url = DEFAULT_URL
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--url" and i + 1 < len(args):
            url = args[i + 1]

    wait_for_server(url)

    from lunagrow_biosim.run import main
    sys.argv = ["run.py"] + args
    main()
