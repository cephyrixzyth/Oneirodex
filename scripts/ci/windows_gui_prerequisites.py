"""Ordinary fixture child only: fixed Win32 observations, no app or browser."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import uuid


CHECKS = ('own_mutex', 'browser_mutex_open', 'message_window', 'lock_file')


def collect_checks(api, lock_path):
    result = {'schema_version': 1}
    for key, function in zip(CHECKS, (api.own_mutex, api.browser_mutex,
                                    api.message_window, lambda: api.lock_file(lock_path))):
        succeeded, error = function()
        result[key] = {'succeeded': succeeded, 'win32_error': error}
    result['owned_prerequisites_passed'] = all(result[key]['succeeded']
                                              for key in CHECKS if key != 'browser_mutex_open')
    return result


class NativeGUIAPI:
    def __init__(self):
        import ctypes as c
        from ctypes import wintypes as w
        self.c = c
        kernel, user = c.WinDLL('kernel32', use_last_error=True), c.WinDLL('user32', use_last_error=True)
        def bind(lib, name, restype, args):
            function = getattr(lib, name)
            function.restype, function.argtypes = restype, args
            return function
        self._create_mutex = bind(kernel, 'CreateMutexW', w.HANDLE, [c.c_void_p, w.BOOL, w.LPCWSTR])
        self._open_mutex = bind(kernel, 'OpenMutexW', w.HANDLE, [w.DWORD, w.BOOL, w.LPCWSTR])
        self._close = bind(kernel, 'CloseHandle', w.BOOL, [w.HANDLE])
        self._create_window = bind(user, 'CreateWindowExW', w.HWND,
                                   [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, c.c_int, c.c_int,
                                    c.c_int, c.c_int, w.HWND, w.HMENU, w.HINSTANCE, c.c_void_p])
        self._destroy_window = bind(user, 'DestroyWindow', w.BOOL, [w.HWND])
        self._create_file = bind(kernel, 'CreateFileW', w.HANDLE,
                                [w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p, w.DWORD, w.DWORD, w.HANDLE])

    def _finish(self, handle, closer):
        if not closer(handle):
            return False, int(self.c.get_last_error())
        return True, 0

    def own_mutex(self):
        self.c.set_last_error(0)
        handle = self._create_mutex(None, False, 'Local\\oneirodex-fixture-' + uuid.uuid4().hex)
        error = int(self.c.get_last_error())
        if not handle:
            return False, error
        closed = self._finish(handle, self._close)
        return (False, error) if error == 183 else closed  # Never accept a pre-existing collision.

    def browser_mutex(self):
        # Open/close only: never CreateMutex, wait, acquire, release or change this foreign object.
        # Match upstream CreateMutex's existing-object access request, not a weaker access mask.
        handle = self._open_mutex(0x1F0001, False, 'Local\\ChromeProcessSingletonStartup!')
        if not handle:
            return False, int(self.c.get_last_error())
        return self._finish(handle, self._close)

    def message_window(self):
        handle = self._create_window(0, 'STATIC', None, 0, 0, 0, 0, 0,
                                     self.c.c_void_p(-3), None, None, None)  # HWND_MESSAGE; invisible.
        if not handle:
            return False, int(self.c.get_last_error())
        return self._finish(handle, self._destroy_window)

    def lock_file(self, path):
        handle = self._create_file(str(path), 0x40010000, 1, None, 1, 0x04000080, None)
        if handle == self.c.c_void_p(-1).value:
            return False, int(self.c.get_last_error())
        closed = self._finish(handle, self._close)
        return closed if not closed[0] or not path.exists() else (False, 0)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    # The controller enforces real CI and checks the suspended child SID/token/profile before resume.
    # This additional child fence refuses an ordinary local invocation before native/file access.
    if (os.name != 'nt' or not re.fullmatch(r'odci[0-9a-f]{12}', os.environ.get('USERNAME', ''))
            or args.output.name != 'gui-prerequisites.json'
            or not re.fullmatch(r'oneirodex-standard-user-fixture-[1-9][0-9]*', args.output.parent.name)):
        return 2
    try:
        result = collect_checks(NativeGUIAPI(), args.output.parent / 'gui-prerequisites.lock')
        with args.output.open('x', encoding='utf-8') as target:
            json.dump(result, target)
        return 0
    except Exception:
        return 1  # Raw native exceptions/paths never leave the child.


if __name__ == '__main__':
    sys.exit(main())
