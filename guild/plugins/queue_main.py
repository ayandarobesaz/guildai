# Copyright 2017-2019 TensorHub, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import absolute_import
from __future__ import division

import argparse
import logging
import os
import time

from guild import _api as gapi
from guild import lock as locklib
from guild import op_util
from guild import util
from guild import var

logging.basicConfig(
    level=int(os.getenv("LOG_LEVEL", logging.INFO)),
    format="%(levelname)s: [%(name)s] %(asctime)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

RUN_STATUS_LOCK_TIMEOUT = 30

log = logging.getLogger("queue")


class _State(object):
    def __init__(self, args):
        for name, val in args._get_kwargs():
            setattr(self, name, val)
        self.run_id = os.environ["RUN_ID"]
        self.logged_waiting = False
        self.waiting = set()
        self.lock = locklib.Lock(locklib.RUN_STATUS, timeout=RUN_STATUS_LOCK_TIMEOUT)


def main():
    args = _parse_args()
    if args.run_once:
        run_once(args)
    else:
        poll(args)


def _parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--poll-interval", type=int, default=10)
    p.add_argument("--run-once", action="store_true")
    p.add_argument("--ignore-running", action="store_true")
    return p.parse_args()


def run_once(args):
    log.info("Processing staged runs")
    _run_staged(_State(args))


def poll(args):
    state = _State(args)
    util.loop(lambda: _run_staged(state), time.sleep, args.poll_interval, 0)


def _run_staged(state):
    while True:
        run = _safe_next_run(state)
        if not run:
            break
        _start_run(run, state)
    if not state.logged_waiting:
        _log_waiting(state)


def _safe_next_run(state):
    """Uses a system wide lock to get the next run."""
    try:
        state.lock.acquire()
    except locklib.Timeout as e:
        log.warning(
            "could not acquire lock for reading staged runs\n"
            "If this error persists, try stopping all queues and "
            "deleting %s",
            e.lock_file,
        )
        return None
    else:
        return _next_run(state)
    finally:
        state.lock.release()


def _next_run(state):
    """Returns the next run for the queue.

    Note that this call is NOT safe across multiple queue
    instances. Use `safe_next_run` to ensure that multiple queues is
    proper locking.
    """
    for run in _staged_runs():
        if not state.ignore_running:
            running = _running(state)
            if running:
                if run.id not in state.waiting:
                    log.info(
                        "Found staged run %s (waiting for runs " "to finish: %s)",
                        run.short_id,
                        _runs_desc(running),
                    )
                    state.logged_waiting = True
                state.waiting.add(run.id)
                continue
        op_util.set_run_pending(run)
        return run
    return None


def _staged_runs():
    return var.runs(
        sort=["timestamp"], filter=var.run_filter("attr", "status", "staged")
    )


def _running(state):
    running = var.runs(filter=var.run_filter("attr", "status", "running"))
    return [run for run in running if run.id != state.run_id]


def _runs_desc(runs):
    return ", ".join([run.short_id for run in runs])


def _start_run(run, state):
    log.info("Starting staged run %s", run.id)
    try:
        _run(run)
    except gapi.RunError as e:
        log.error("%s failed with exit code %i", run.id, e.returncode)
    state.waiting.clear()
    state.logged_waiting = False


def _run(run):
    env = {
        "NO_RESTARTING_MSG": "1",
        "PYTHONPATH": run.guild_path("job-packages"),
    }
    gapi.run(restart=run.id, extra_env=env)


def _log_waiting(state):
    if not state.run_once:
        log.info("Waiting for staged runs")
    state.logged_waiting = True


if __name__ == "__main__":
    main()
