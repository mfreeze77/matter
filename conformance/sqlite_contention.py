"""MAT-083 synthetic real-handle diagnostic; no timeout, SQL or retry changes.

Run with PYTHONPATH=tests. --profile deliberately adds measurement overhead;
--disable-validation-cache restores repeated structural checks for comparison.
Neither option belongs in a production process. Nonzero means the ORIGINAL
race assertion failed; a busy result is never reclassified as suppression.
"""
import argparse
from contextlib import ExitStack
import cProfile
import json
import platform
import sqlite3
import sys
import threading
import time
import unittest
from unittest.mock import patch


class ProfileUnavailable(ValueError):
    """This diagnostic has no validated concurrent profiler on this interpreter."""


def run(*, profile=False, disable_validation_cache=False):
    if profile and sys.version_info[:2] != (3, 11):
        raise ProfileUnavailable("Concurrent profiler mode requires Python 3.11; omit --profile for transaction traces on other versions.")
    from matter import __version__
    from matter.storage import SQLiteStore
    from integration.test_dispatch_races import DispatchRaces

    local = threading.local()
    events = []
    lock = threading.Lock()
    original_connect = sqlite3.connect
    original_execute = SQLiteStore.execute

    def emit(**values):
        with lock:
            events.append(dict(at=time.perf_counter(), **values))

    class TracedConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            command = getattr(local, 'command', None)
            if not command:
                return super().execute(sql, *args, **kwargs)
            verb = sql.split(None, 1)[0].upper()
            selected = verb in {'BEGIN', 'SAVEPOINT', 'RELEASE', 'COMMIT', 'ROLLBACK'}
            if selected:
                emit(command=command, event=verb + '_enter')
            started = time.perf_counter()
            try:
                result = super().execute(sql, *args, **kwargs)
            except sqlite3.Error as error:
                emit(command=command, event='sqlite_error', verb=verb,
                     code=getattr(error, 'sqlite_errorcode', None),
                     name=getattr(error, 'sqlite_errorname', None),
                     seconds=time.perf_counter() - started)
                raise
            if selected:
                emit(command=command, event=verb + '_exit', seconds=time.perf_counter() - started)
            return result

        def commit(self):
            command = getattr(local, 'command', None)
            if command:
                emit(command=command, event='commit_enter')
            result = super().commit()
            if command:
                emit(command=command, event='commit_exit')
            return result

    def connect(*args, **kwargs):
        # SQLiteStore supplies no factory. Preserve all its normal options,
        # including the unmodified five-second timeout and journal mode.
        kwargs['factory'] = TracedConnection
        return original_connect(*args, **kwargs)

    def execute(store, command, *args, **kwargs):
        if command.get('operation') != 'prepare_delivery' or command.get('command_id') not in {'intent-a', 'intent-b'}:
            return original_execute(store, command, *args, **kwargs)
        local.command = command['command_id']
        started = time.perf_counter()
        emit(command=local.command, event='execute_enter')
        profiler = cProfile.Profile() if profile else None
        try:
            if profiler is not None:
                profiler.enable()
            result = original_execute(store, command, *args, **kwargs)
            if profiler is not None:
                profiler.disable()
            emit(command=local.command, event='execute_result', outcome=result.get('outcome'),
                 error=result.get('error', {}).get('code'), seconds=time.perf_counter() - started)
            return result
        finally:
            if profiler is not None:
                profiler.disable()
                emit(command=local.command, event='profile_summary',
                     function_calls=sum(x.callcount for x in profiler.getstats()))
            local.command = None

    case = DispatchRaces('test_distinct_equivalent_intents_compete_across_real_sqlite_handles')
    started = time.perf_counter()
    with ExitStack() as stack:
        if disable_validation_cache:
            import matter._validation as validation
            stack.enter_context(patch.object(validation, '_SUCCESSFUL', validation.ValidationCache(max_entries=0)))
        stack.enter_context(patch.object(sqlite3, 'connect', connect))
        stack.enter_context(patch.object(SQLiteStore, 'execute', execute))
        result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([case]))
    return dict(python=platform.python_version(), sqlite=sqlite3.sqlite_version,
                sdk=__version__, profiled=profile, validation_cache_disabled=disable_validation_cache,
                success=result.wasSuccessful(), seconds=time.perf_counter() - started, events=events)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', action='store_true')
    parser.add_argument('--disable-validation-cache', action='store_true')
    args = parser.parse_args()
    try:
        report = run(profile=args.profile, disable_validation_cache=args.disable_validation_cache)
    except ProfileUnavailable as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2))
    return int(not report['success'])


if __name__ == '__main__':
    raise SystemExit(main())
