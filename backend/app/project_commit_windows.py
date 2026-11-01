"""Windows NTFS copy-on-write commit; never writes the original file object.

Two non-overwriting handle renames deliberately are not a crash-atomic swap.
Callers must durably journal original bytes before invoking this module.
"""
import hashlib
import ntpath
import os
import secrets

from .project_files import MAX_EDIT_BYTES, MAX_EDIT_CHARS, MAX_EDIT_LINES, ProjectFileError, text_line_count


def error(code, status=422):
    messages = {"unsupported": "当前文件或系统不支持受控修改。", "conflict": "文件版本已变化，未覆盖当前文件。",
                "busy": "文件正在被其它程序使用，请关闭后重试。", "failed": "修改未完成，请查看恢复记录。"}
    return ProjectFileError("project_change_" + code, messages.get(code, "项目修改请求失败。"), status)


if os.name == "nt":
    import ctypes
    from ctypes import wintypes
    import msvcrt
    from . import project_files as files

    K = files._kernel
    A = ctypes.WinDLL("advapi32", use_last_error=True)
    K.GetVolumeInformationW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR, wintypes.DWORD]
    K.GetVolumeInformationW.restype = wintypes.BOOL
    K.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    K.GetFileInformationByHandleEx.restype = wintypes.BOOL
    K.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    K.SetFileInformationByHandle.restype = wintypes.BOOL
    A.GetKernelObjectSecurity.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    A.GetKernelObjectSecurity.restype = wintypes.BOOL
    for name in ("GetSecurityDescriptorOwner", "GetSecurityDescriptorGroup"):
        function = getattr(A, name)
        function.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
        function.restype = wintypes.BOOL
    A.GetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
    A.GetSecurityDescriptorDacl.restype = wintypes.BOOL
    A.GetSecurityDescriptorSacl.argtypes = A.GetSecurityDescriptorDacl.argtypes
    A.GetSecurityDescriptorSacl.restype = wintypes.BOOL
    A.GetSecurityDescriptorControl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.WORD), ctypes.POINTER(wintypes.DWORD)]
    A.GetSecurityDescriptorControl.restype = wintypes.BOOL
    A.GetLengthSid.argtypes = [ctypes.c_void_p]
    A.GetLengthSid.restype = wintypes.DWORD
    A.SetSecurityInfo.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    A.SetSecurityInfo.restype = wintypes.DWORD

    class _RenameInfo(ctypes.Structure):
        _fields_ = [("replace", wintypes.DWORD), ("root", wintypes.HANDLE), ("name_length", wintypes.DWORD), ("name", wintypes.WCHAR * 1)]


def supported(path):
    if os.name != "nt":
        return False
    filesystem = ctypes.create_unicode_buffer(32)
    drive = ntpath.splitdrive(str(path))[0] + "\\"
    return bool(K.GetVolumeInformationW(drive, None, 0, None, None, None, filesystem, len(filesystem))) and filesystem.value == "NTFS"


def _open(path, *, create=False):
    # GENERIC_WRITE verifies real write permission even though old bytes are
    # never written; WRITE_DAC is required only on the new private staging file.
    access = 0xC0010000 | (0x00040000 if create else 0)
    handle = K.CreateFileW(str(path), access, 0, None, 1 if create else 3, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        code = ctypes.get_last_error()
        raise error("busy" if code in (32, 33) else "unsupported", 409 if code in (32, 33) else 422)
    return handle


def _label(handle):
    size = wintypes.DWORD()
    A.GetKernelObjectSecurity(handle, 0x10, None, 0, ctypes.byref(size))
    if not 20 <= size.value <= 65536:
        raise error("unsupported")
    buffer = ctypes.create_string_buffer(size.value)
    if not A.GetKernelObjectSecurity(handle, 0x10, buffer, len(buffer), ctypes.byref(size)):
        raise error("unsupported")
    present, defaulted, acl = wintypes.BOOL(), wintypes.BOOL(), ctypes.c_void_p()
    if not A.GetSecurityDescriptorSacl(buffer, ctypes.byref(present), ctypes.byref(acl), ctypes.byref(defaulted)):
        raise error("unsupported")
    if not present.value or not acl.value:
        return b""
    length = ctypes.c_ushort.from_address(acl.value + 2).value
    if not 8 <= length <= 65535:
        raise error("unsupported")
    return ctypes.string_at(acl, length)


def _reject_readable_audit_acl(handle):
    # Do not enable SeSecurityPrivilege. Ordinary handles generally cannot read
    # audit SACLs; the documented support boundary excludes custom audit rules.
    size = wintypes.DWORD()
    ctypes.set_last_error(0)
    A.GetKernelObjectSecurity(handle, 8, None, 0, ctypes.byref(size))
    if not size.value and ctypes.get_last_error() in (5, 1314):
        return
    if not 20 <= size.value <= 65536:
        raise error("unsupported")
    buffer = ctypes.create_string_buffer(size.value)
    if not A.GetKernelObjectSecurity(handle, 8, buffer, len(buffer), ctypes.byref(size)):
        if ctypes.get_last_error() in (5, 1314):
            return
        raise error("unsupported")
    present, defaulted, acl = wintypes.BOOL(), wintypes.BOOL(), ctypes.c_void_p()
    if not A.GetSecurityDescriptorSacl(buffer, ctypes.byref(present), ctypes.byref(acl), ctypes.byref(defaulted)):
        raise error("unsupported")
    if not present.value or not acl.value:
        return
    length = ctypes.c_ushort.from_address(acl.value + 2).value
    count = ctypes.c_ushort.from_address(acl.value + 4).value
    offset = 8
    for _ in range(count):
        if offset + 4 > length:
            raise error("unsupported")
        ace_type = ctypes.c_ubyte.from_address(acl.value + offset).value
        ace_size = ctypes.c_ushort.from_address(acl.value + offset + 2).value
        if ace_type != 0x11 or ace_size < 4 or offset + ace_size > length:
            raise error("unsupported")
        offset += ace_size


def _security(handle):
    size = wintypes.DWORD()
    A.GetKernelObjectSecurity(handle, 7, None, 0, ctypes.byref(size))
    if not 20 <= size.value <= 65536:
        raise error("unsupported")
    buffer = ctypes.create_string_buffer(size.value)
    if not A.GetKernelObjectSecurity(handle, 7, buffer, len(buffer), ctypes.byref(size)):
        raise error("unsupported")
    owner, group, dacl = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    defaulted, present = wintypes.BOOL(), wintypes.BOOL()
    control, revision = wintypes.WORD(), wintypes.DWORD()
    if not (A.GetSecurityDescriptorOwner(buffer, ctypes.byref(owner), ctypes.byref(defaulted))
            and A.GetSecurityDescriptorGroup(buffer, ctypes.byref(group), ctypes.byref(defaulted))
            and A.GetSecurityDescriptorDacl(buffer, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted))
            and A.GetSecurityDescriptorControl(buffer, ctypes.byref(control), ctypes.byref(revision))
            and owner.value and group.value and present.value and dacl.value):
        raise error("unsupported")
    if control.value & 0x2000:
        # A protected audit SACL is outside the ordinary-user-file contract.
        raise error("unsupported")
    _reject_readable_audit_acl(handle)
    acl_size = ctypes.c_ushort.from_address(dacl.value + 2).value
    if not 8 <= acl_size <= 65535:
        raise error("unsupported")
    return {"owner": ctypes.string_at(owner, A.GetLengthSid(owner)), "group": ctypes.string_at(group, A.GetLengthSid(group)),
            "dacl": ctypes.string_at(dacl, acl_size), "protected": bool(control.value & 0x1000), "label": _label(handle)}


def _copy_security(original, staging):
    old, new = _security(original), _security(staging)
    if any(old[key] != new[key] for key in ("owner", "group", "label")):
        raise error("unsupported")
    acl = ctypes.create_string_buffer(old["dacl"])
    flags = 4 | (0x80000000 if old["protected"] else 0x20000000)
    if A.SetSecurityInfo(staging, 1, flags, None, None, acl, None):
        raise error("unsupported")
    if _security(staging) != old:
        raise error("unsupported")


def _streams(handle):
    buffer = ctypes.create_string_buffer(65536)
    if not K.GetFileInformationByHandleEx(handle, 7, buffer, len(buffer)):
        raise error("unsupported")
    offset = 0
    while True:
        if offset + 24 > len(buffer):
            raise error("unsupported")
        next_offset = int.from_bytes(buffer.raw[offset:offset + 4], "little")
        name_size = int.from_bytes(buffer.raw[offset + 4:offset + 8], "little")
        if name_size > len(buffer) - offset - 24 or name_size % 2:
            raise error("unsupported")
        name = buffer.raw[offset + 24:offset + 24 + name_size].decode("utf-16-le", errors="strict")
        if name != "::$DATA" or next_offset:
            raise error("unsupported")
        return


def _rename(handle, destination):
    encoded = str(destination).encode("utf-16-le")
    buffer = ctypes.create_string_buffer(_RenameInfo.name.offset + len(encoded) + 2)
    info = _RenameInfo.from_buffer(buffer)
    info.replace, info.root, info.name_length = 0, None, len(encoded)
    ctypes.memmove(ctypes.addressof(buffer) + _RenameInfo.name.offset, encoded, len(encoded))
    if not K.SetFileInformationByHandle(handle, 3, buffer, len(buffer)):
        raise ctypes.WinError(ctypes.get_last_error())
    if ntpath.normcase(files._win_final(handle)) != ntpath.normcase(str(destination)):
        raise OSError("rename verification failed")


def _delete(handle):
    flag = ctypes.c_ubyte(1)
    return bool(K.SetFileInformationByHandle(handle, 4, ctypes.byref(flag), 1))


def _read(fd):
    os.lseek(fd, 0, os.SEEK_SET)
    chunks = bytearray()
    while len(chunks) <= MAX_EDIT_BYTES:
        chunk = os.read(fd, MAX_EDIT_BYTES + 1 - len(chunks))
        if not chunk:
            break
        chunks.extend(chunk)
    return bytes(chunks)


def _write_all(fd, raw):
    offset = 0
    while offset < len(raw):
        count = os.write(fd, raw[offset:])
        if count <= 0:
            raise OSError("short write")
        offset += count
    os.ftruncate(fd, len(raw))


def _flush(fd):
    os.fsync(fd)


def _valid_raw(raw):
    try:
        text = raw.decode("utf-8-sig", errors="strict")
    except (UnicodeError, AttributeError):
        raise error("unsupported") from None
    if (len(raw) > MAX_EDIT_BYTES or len(text) > MAX_EDIT_CHARS or text_line_count(text) > MAX_EDIT_LINES
            or any(ord(c) < 32 and c not in "\r\n\t" or ord(c) == 127 for c in text)):
        raise error("unsupported")


def commit_file(parent, path, volume, expected_identity, expected_sha256, replacement, checkpoint):
    if not supported(path):
        raise error("unsupported")
    _valid_raw(replacement)
    original = _open(path)
    original_fd = staging = stage_fd = None
    moved = published = False
    stage_name = ".campus-stage-" + secrets.token_hex(16) + ".tmp"
    backup_name = ".campus-backup-" + secrets.token_hex(16) + ".tmp"
    stage_path, backup_path = parent / stage_name, parent / backup_name
    details = {"stage_name": stage_name, "backup_name": backup_name}
    try:
        info = files._win_check(original, path, directory=False, volume=volume)
        # Only ordinary archive/normal attributes are supported; all metadata
        # whose replacement semantics would otherwise be lost is fail-closed.
        if info.attributes & ~0xA0:
            raise error("unsupported")
        _streams(original)
        old_security = _security(original)
        original_fd = msvcrt.open_osfhandle(original, os.O_RDWR | os.O_BINARY)
        original = None
        old_handle = msvcrt.get_osfhandle(original_fd)
        old_raw = _read(original_fd)
        _valid_raw(old_raw)
        identity = (os.fstat(original_fd).st_dev, os.fstat(original_fd).st_ino)
        if identity != tuple(expected_identity) or hashlib.sha256(old_raw).hexdigest() != expected_sha256:
            raise error("conflict", 409)
        checkpoint("planned", details)
        staging = _open(stage_path, create=True)
        files._win_check(staging, stage_path, directory=False, volume=volume)
        _copy_security(old_handle, staging)
        stage_fd = msvcrt.open_osfhandle(staging, os.O_RDWR | os.O_BINARY)
        staging = None
        stage_handle = msvcrt.get_osfhandle(stage_fd)
        details["after_identity"] = (os.fstat(stage_fd).st_dev, os.fstat(stage_fd).st_ino)
        try:
            _write_all(stage_fd, replacement)
            _flush(stage_fd)
            if _read(stage_fd) != replacement or _security(old_handle) != old_security:
                raise OSError("staging verification failed")
            checkpoint("prepared", details)
            _rename(old_handle, backup_path)
            moved = True
            checkpoint("original_moved", details)
            _rename(stage_handle, path)
            published = True
            if _read(stage_fd) != replacement:
                raise OSError("publication verification failed")
            checkpoint("published", details)
            cleaned = _delete(old_handle)
            return {"state": "applied" if cleaned else "uncertain", **details,
                    **({} if cleaned else {"error_code": "project_change_failed", "backup_retained": True})}
        except Exception:
            # Rename can succeed before final-path validation or a callback
            # fails. Infer phase from the still-open objects, never from only
            # the Python assignment following the syscall.
            try:
                published = published or ntpath.normcase(files._win_final(stage_handle)) == ntpath.normcase(str(path))
                moved = moved or ntpath.normcase(files._win_final(old_handle)) != ntpath.normcase(str(path))
            except ProjectFileError:
                return {"state": "uncertain", "error_code": "project_change_failed", **details}
            if published:
                # A callback/journal failure cannot make a completed publication
                # safe to repeat. Durable pending state is reconciled by GET.
                return {"state": "uncertain", "error_code": "project_change_failed", **details}
            restored = not moved and _read(original_fd) == old_raw
            if moved:
                try:
                    _rename(old_handle, path)
                    restored = _read(original_fd) == old_raw
                except OSError:
                    restored = False
            return {"state": "failed" if restored else "uncertain", "error_code": "project_change_failed", **details}
    finally:
        if stage_fd is not None:
            if not published:
                _delete(msvcrt.get_osfhandle(stage_fd))
            os.close(stage_fd)
        elif staging is not None:
            _delete(staging)
            K.CloseHandle(staging)
        if original_fd is not None:
            os.close(original_fd)
        elif original is not None:
            K.CloseHandle(original)
