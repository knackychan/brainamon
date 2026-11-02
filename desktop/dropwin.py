"""Drag and drop onto a native window on Windows (projects/desktop-app plan 07b): an OLE IDropTarget
written with ctypes, so the tkinter widget accepts files from Explorer and links or text from a
browser without an extra package (tkinter has no drop support of its own).

    target = dropwin.register(hwnd, on_enter, on_leave, on_drop, on_over)   # None when OLE is not available
    dropwin.revoke(hwnd)                                                     # before the window is destroyed

on_enter(kind, payload, x, y) runs when something droppable comes over the window (what it is, read
at once: ('files', [paths]), ('url', str) or ('text', str), and the cursor's screen point);
on_over(x, y) while it moves over the window (plan 11: the drop ring highlights a bubble);
on_leave() when it leaves; on_drop(kind, payload, x, y) on the drop (on_leave runs first).
None of them runs inside the OLE call: OLE calls back from inside Tcl's event loop, and entering
tkinter there clears _tkinter's thread state, so the next Tcl callback aborts Python ("PyEval_RestoreThread:
the function must be called with the GIL held"). The calls queue up in order instead; the tk side runs
them with pump() from an after() timer.
Keep the returned object alive as long as the window: it owns the COM vtable and callbacks.
"""
import collections
import ctypes
import struct
import sys
from ctypes import wintypes as wt

HRESULT = ctypes.c_long
S_OK = 0
E_NOINTERFACE = -2147467262          # 0x80004002
DROPEFFECT_NONE, DROPEFFECT_COPY, DROPEFFECT_LINK = 0, 1, 4
CF_UNICODETEXT, CF_HDROP = 13, 15
TYMED_HGLOBAL = 1
DVASPECT_CONTENT = 1

_IID_IUNKNOWN = struct.pack('<IHH8B', 0, 0, 0, 0xC0, 0, 0, 0, 0, 0, 0, 0x46)
_IID_IDROPTARGET = struct.pack('<IHH8B', 0x122, 0, 0, 0xC0, 0, 0, 0, 0, 0, 0, 0x46)

_queue = collections.deque()         # (callback, args) from OLE calls, for pump(); deque appends are thread safe


class FORMATETC(ctypes.Structure):
    _fields_ = [('cfFormat', wt.WORD), ('ptd', ctypes.c_void_p), ('dwAspect', wt.DWORD),
                ('lindex', wt.LONG), ('tymed', wt.DWORD)]


class STGMEDIUM(ctypes.Structure):
    _fields_ = [('tymed', wt.DWORD), ('hGlobal', ctypes.c_void_p), ('pUnkForRelease', ctypes.c_void_p)]


# IDropTarget methods. POINTL (two LONGs, 8 bytes) is passed by value: an int64 in the x64 ABI.
_QI = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
_REF = ctypes.WINFUNCTYPE(wt.ULONG, ctypes.c_void_p)
_ENTER = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.c_int64, ctypes.POINTER(wt.DWORD))
_OVER = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, wt.DWORD, ctypes.c_int64, ctypes.POINTER(wt.DWORD))
_LEAVE = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p)

# IDataObject methods used (vtable slots 3 and 5)
_GETDATA = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.POINTER(FORMATETC), ctypes.POINTER(STGMEDIUM))
_QUERYGETDATA = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.POINTER(FORMATETC))


class _Vtbl(ctypes.Structure):
    _fields_ = [('QueryInterface', _QI), ('AddRef', _REF), ('Release', _REF), ('DragEnter', _ENTER),
                ('DragOver', _OVER), ('DragLeave', _LEAVE), ('Drop', _ENTER)]


class _Obj(ctypes.Structure):
    _fields_ = [('vtbl', ctypes.POINTER(_Vtbl))]


def point(pt: int) -> tuple[int, int]:
    """POINTL passed by value as one int64 (x64 ABI): x in the low 32 bits, y in the high, both signed."""
    return struct.unpack('<ii', struct.pack('<q', pt))


def _effect(allowed: int) -> int:
    if allowed & DROPEFFECT_COPY:
        return DROPEFFECT_COPY
    return DROPEFFECT_LINK if allowed & DROPEFFECT_LINK else DROPEFFECT_NONE


class _Data:
    """Read what is being dragged from an IDataObject pointer (valid only inside the OLE call)."""

    def __init__(self, ptr):
        self.ptr = ptr
        vt = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        self._get = _GETDATA(vt[3])
        self._has = _QUERYGETDATA(vt[5])

    @staticmethod
    def _fmt(cf: int) -> FORMATETC:
        return FORMATETC(cf, None, DVASPECT_CONTENT, -1, TYMED_HGLOBAL)

    def has(self, cf: int) -> bool:
        return self._has(self.ptr, ctypes.byref(self._fmt(cf))) == S_OK

    def read(self, cf: int, fn):
        fe, sm = self._fmt(cf), STGMEDIUM()
        if self._get(self.ptr, ctypes.byref(fe), ctypes.byref(sm)) != S_OK:
            return None
        try:
            return fn(sm.hGlobal)
        finally:
            _ole32.ReleaseStgMedium(ctypes.byref(sm))


def _files(h) -> list[str]:
    n = _shell32.DragQueryFileW(h, 0xFFFFFFFF, None, 0)
    out = []
    for i in range(n):
        size = _shell32.DragQueryFileW(h, i, None, 0)
        buf = ctypes.create_unicode_buffer(size + 1)
        _shell32.DragQueryFileW(h, i, buf, size + 1)
        out.append(buf.value)
    return out


def _wtext(h) -> str:
    p = _kernel32.GlobalLock(h)
    try:
        return ctypes.wstring_at(p) if p else ''
    finally:
        _kernel32.GlobalUnlock(h)


def classify(files: list[str] | None, url: str | None, text: str | None):
    """What a drop is, in the order Brainamon files it: files, then a link, then plain text."""
    if files:
        return 'files', files
    url = (url or '').strip().splitlines()[0] if (url or '').strip() else ''
    if url:
        return 'url', url
    text = (text or '').strip()
    if text:
        return 'text', text
    return None


class DropTarget:
    def __init__(self, on_enter, on_leave, on_drop, on_over=None):
        self.on_enter, self.on_leave, self.on_drop = on_enter, on_leave, on_drop
        self.on_over = on_over or (lambda x, y: None)
        self.ok = False
        self.cf_url = _user32.RegisterClipboardFormatW('UniformResourceLocatorW')
        self._vt = _Vtbl(_QI(self._qi), _REF(lambda this: 2), _REF(lambda this: 1), _ENTER(self._enter),
                         _OVER(self._over), _LEAVE(self._leave), _ENTER(self._drop))
        self.obj = _Obj(ctypes.pointer(self._vt))

    def _qi(self, this, riid, ppv):
        iid = ctypes.string_at(riid, 16)
        if iid in (_IID_IUNKNOWN, _IID_IDROPTARGET):
            ppv[0] = this
            return S_OK
        ppv[0] = None
        return E_NOINTERFACE

    def _read(self, d: _Data):
        return classify(d.read(CF_HDROP, _files) if d.has(CF_HDROP) else None,
                        d.read(self.cf_url, _wtext) if d.has(self.cf_url) else None,
                        d.read(CF_UNICODETEXT, _wtext) if d.has(CF_UNICODETEXT) else None)

    def _enter(self, this, data, keys, pt, effect):
        try:
            got = self._read(_Data(data))
            self.ok = got is not None
            effect[0] = _effect(effect[0]) if self.ok else DROPEFFECT_NONE
            if self.ok:
                self._post(self.on_enter, *got, *point(pt))
        except Exception:
            self.ok, effect[0] = False, DROPEFFECT_NONE
        return S_OK

    def _over(self, this, keys, pt, effect):
        effect[0] = _effect(effect[0]) if self.ok else DROPEFFECT_NONE
        if self.ok:
            self._post(self.on_over, *point(pt))
        return S_OK

    def _leave(self, this):
        if self.ok:
            self._post(self.on_leave)
        self.ok = False
        return S_OK

    def _drop(self, this, data, keys, pt, effect):
        try:
            got = self._read(_Data(data))
            effect[0] = _effect(effect[0]) if got else DROPEFFECT_NONE
        except Exception:
            got, effect[0] = None, DROPEFFECT_NONE
        self.ok = False
        self._post(self.on_leave)
        if got:
            self._post(self.on_drop, *got, *point(pt))
        return S_OK

    @staticmethod
    def _post(fn, *a):
        _queue.append((fn, a))


def pump() -> None:
    """Run the queued drop callbacks, oldest first (call it from a tk after() timer, never from OLE)."""
    while _queue:
        fn, a = _queue.popleft()
        try:
            fn(*a)
        except Exception:
            pass


def _hwnds(hwnds) -> list:
    return list(hwnds) if isinstance(hwnds, (list, tuple)) else [hwnds]


def register(hwnds, on_enter, on_leave, on_drop, on_over=None):
    """Make these windows (an HWND or a list) drop targets. Returns the DropTarget, or None."""
    if sys.platform != 'win32':
        return None
    hr = _ole32.OleInitialize(None)
    if hr not in (0, 1):                 # S_OK, S_FALSE (already initialized on this thread)
        return None
    t = DropTarget(on_enter, on_leave, on_drop, on_over)
    done = 0
    for h in _hwnds(hwnds):
        if _ole32.RegisterDragDrop(wt.HWND(h), ctypes.byref(t.obj)) == S_OK:
            done += 1
    return t if done else None


def revoke(hwnds) -> None:
    """Undo register() for windows about to be destroyed (the drop ring)."""
    if sys.platform != 'win32':
        return
    for h in _hwnds(hwnds):
        _ole32.RevokeDragDrop(wt.HWND(h))


if sys.platform == 'win32':
    _ole32 = ctypes.windll.ole32
    _shell32 = ctypes.windll.shell32
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
    _ole32.OleInitialize.argtypes = [ctypes.c_void_p]
    _ole32.RegisterDragDrop.argtypes = [wt.HWND, ctypes.c_void_p]
    _ole32.RevokeDragDrop.argtypes = [wt.HWND]
    _ole32.ReleaseStgMedium.argtypes = [ctypes.c_void_p]
    _shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, wt.UINT, ctypes.c_wchar_p, wt.UINT]
    _shell32.DragQueryFileW.restype = wt.UINT
    _user32.RegisterClipboardFormatW.argtypes = [wt.LPCWSTR]
    _user32.RegisterClipboardFormatW.restype = wt.UINT
    _kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    _kernel32.GlobalLock.restype = ctypes.c_void_p
    _kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
