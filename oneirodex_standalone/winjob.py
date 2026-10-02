"""Windows: end the launcher's children with it, however it ends.

Ctrl+C or closing the console runs the launcher's shutdown, which stops the web
server and PostgreSQL. Ending it from Task Manager (or any hard kill) does not:
Windows has no process groups that die together, so both used to keep running,
the database holding its data folder and the web port still answering.

A Job Object flagged KILL_ON_JOB_CLOSE fixes that. The launcher puts itself in
one at start-up; every process it starts afterwards joins the same job, and
when the launcher process dies by any route its handle to the job is closed and
Windows ends every process left in it. PostgreSQL then recovers on the next
start the way it does after any crash.
"""
from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)

_JOB = None  # kept open for the life of the process; closing it ends the children

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000


def tie_children_to_this_process() -> bool:
    """Make every process started from now on end with this one (Windows only).

    Returns True when the job is in place. Anywhere else, or if Windows refuses
    (a parent job that forbids nesting), it returns False and the launcher
    carries on with its normal shutdown handling.
    """
    global _JOB
    if sys.platform != 'win32' or _JOB is not None:
        return _JOB is not None
    import ctypes
    from ctypes import wintypes

    class _IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            'ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
            'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]

    class _BasicLimits(ctypes.Structure):
        _fields_ = [
            ('PerProcessUserTimeLimit', ctypes.c_int64),
            ('PerJobUserTimeLimit', ctypes.c_int64),
            ('LimitFlags', wintypes.DWORD),
            ('MinimumWorkingSetSize', ctypes.c_size_t),
            ('MaximumWorkingSetSize', ctypes.c_size_t),
            ('ActiveProcessLimit', wintypes.DWORD),
            ('Affinity', ctypes.c_size_t),
            ('PriorityClass', wintypes.DWORD),
            ('SchedulingClass', wintypes.DWORD),
        ]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ('BasicLimitInformation', _BasicLimits),
            ('IoInfo', _IoCounters),
            ('ProcessMemoryLimit', ctypes.c_size_t),
            ('JobMemoryLimit', ctypes.c_size_t),
            ('PeakProcessMemoryUsed', ctypes.c_size_t),
            ('PeakJobMemoryUsed', ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        logger.warning('could not create a Windows job object (error %s); a hard kill may leave PostgreSQL running',
                       ctypes.get_last_error())
        return False
    limits = _ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not (kernel32.SetInformationJobObject(job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                                             ctypes.byref(limits), ctypes.sizeof(limits))
            and kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess())):
        logger.warning('could not join a Windows job object (error %s); a hard kill may leave PostgreSQL running',
                       ctypes.get_last_error())
        kernel32.CloseHandle(job)
        return False
    _JOB = job
    return True
