"""Stable capture and bounded ZIP/tar verification. No archive-owned extraction paths."""
import hashlib
import binascii
import bz2
from contextlib import ExitStack
import gzip
import os
from pathlib import Path
import shutil
import stat
import struct
import tarfile
import zipfile

from .io import EvidenceError, _is_link, _open_regular, _parents, _verify_stable, hash_file, safe_relative

CHUNK = 1024 * 1024


def _safe_directory(path):
    path = Path(os.path.abspath(path))
    for item in [*reversed(path.parents), path]:
        if not item.exists() and not item.is_symlink():
            item.mkdir(mode=0o700)
        info = item.lstat()
        if _is_link(info) or not stat.S_ISDIR(info.st_mode):
            raise EvidenceError("unsafe capture/extraction directory")
    return path


def _open_output(path):
    """Exclusive regular output in a checked directory; never follows a link."""
    path = Path(os.path.abspath(path))
    _safe_directory(path.parent)
    _parents(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    parent_fd = None
    try:
        if os.open in os.supports_dir_fd and hasattr(os, "O_NOFOLLOW"):
            parent_fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            for component in path.parts[1:-1]:
                next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
                os.close(parent_fd)
                parent_fd = next_fd
            fd = os.open(path.name, flags, 0o600, dir_fd=parent_fd)
        else:
            fd = os.open(path, flags, 0o600)
        return os.fdopen(fd, "wb")
    finally:
        if parent_fd is not None:
            os.close(parent_fd)


def _limit(value, name, *, zero=False):
    if type(value) is not int or value < (0 if zero else 1):
        raise EvidenceError(name + " must be a positive integer")
    return value


def capture(source, destination, maximum):
    _limit(maximum, "capture maximum", zero=True)
    destination = Path(os.path.abspath(destination))
    source, descriptor, before = _open_regular(source)
    made_output = False
    try:
        if before.st_size > maximum:
            raise EvidenceError("capture exceeds reserved bytes")
        digest, count = hashlib.sha256(), 0
        with os.fdopen(descriptor, "rb", closefd=False) as src, _open_output(destination) as out:
            made_output = True
            while block := src.read(CHUNK):
                count += len(block)
                if count > maximum:
                    raise EvidenceError("capture grew beyond reservation")
                digest.update(block)
                out.write(block)
            out.flush()
            os.fsync(out.fileno())
        _verify_stable(source, descriptor, before)
        if count != before.st_size:
            raise EvidenceError("capture input changed")
        return {"sha256": digest.hexdigest(), "size": count}
    except BaseException as error:
        if made_output:
            _parents(destination)
            destination.unlink(missing_ok=True)
            if isinstance(error, OSError):
                raise EvidenceError("capture could not preserve stable original bytes: " + str(source)) from error
        raise
    finally:
        os.close(descriptor)


def build_pack(objects, destination, maximum, max_files):
    _limit(maximum, "pack maximum", zero=True)
    _limit(max_files, "pack max_files")
    unique = {}
    for obj in objects:
        if obj["sha256"] in unique and obj["size"] != unique[obj["sha256"]]["size"]:
            raise EvidenceError("conflicting identical-content size")
        unique[obj["sha256"]] = obj
    if len(unique) > max_files or sum(x["size"] for x in unique.values()) > maximum:
        raise EvidenceError("archive pack exceeds reserved content limits")
    members = []
    destination = Path(os.path.abspath(destination))
    made_output = False
    try:
        with _open_output(destination) as pack_output:
            made_output = True
            with zipfile.ZipFile(pack_output, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
                for digest, obj in sorted(unique.items()):
                    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                        raise EvidenceError("invalid captured content identity")
                    source, fd, before = _open_regular(obj["path"])
                    try:
                        if before.st_size != obj["size"]:
                            raise EvidenceError("captured byte size changed before packaging")
                        member = "objects/" + digest
                        info = zipfile.ZipInfo(member, date_time=(1980, 1, 1, 0, 0, 0))
                        info.external_attr = (stat.S_IFREG | 0o600) << 16
                        actual_hash, count = hashlib.sha256(), 0
                        with os.fdopen(fd, "rb", closefd=False) as stream, archive.open(info, "w", force_zip64=True) as output:
                            while block := stream.read(CHUNK):
                                count += len(block)
                                if count > obj["size"]:
                                    raise EvidenceError("captured bytes grew while packaging")
                                actual_hash.update(block)
                                output.write(block)
                        _verify_stable(source, fd, before)
                        if (actual_hash.hexdigest(), count) != (digest, obj["size"]):
                            raise EvidenceError("captured bytes changed while packaging")
                        members.append({"member": member, "sha256": digest, "size": obj["size"]})
                    finally:
                        os.close(fd)
            pack_output.flush()
            os.fsync(pack_output.fileno())
    except BaseException:
        if made_output:
            _parents(destination)
            destination.unlink(missing_ok=True)
        raise
    digest, size = hash_file(destination)
    return {"sha256": digest, "size": size, "members": members}


def _zip_member_name(name):
    # Permit the ZIP directory marker without normalizing repeated separators
    # or archive-controlled backslashes/NULs into apparently safe names.
    safe_relative(name[:-1] if name.endswith("/") else name)


def _zip_raw_names(raw_name, extra, flags):
    try:
        _zip_member_name(raw_name.decode("utf-8" if flags & 0x800 else "cp437"))
        position = 0
        while position + 4 <= len(extra):
            field, length = struct.unpack_from("<HH", extra, position)
            begin, end = position + 4, position + 4 + length
            if end > len(extra):
                raise EvidenceError("invalid ZIP extra field length")
            # CPython can choose this Unicode name and sanitize it separately
            # from orig_filename. Validate that raw alternative before parsing.
            if field == 0x7075:
                if length < 5:
                    raise EvidenceError("invalid ZIP Unicode path extra field")
                version, checksum = struct.unpack_from("<BL", extra, begin)
                if version == 1 and checksum == binascii.crc32(raw_name):
                    alternative = extra[begin + 5:end].decode("utf-8")
                    if alternative:
                        _zip_member_name(alternative)
            position = end
    except UnicodeError as error:
        raise EvidenceError("invalid ZIP member filename encoding") from error


def _zip_preflight(stream, encoded_size, max_files, metadata_limit):
    """Check ZIP central records before ZipFile constructs an entry list."""
    stream.seek(max(0, encoded_size - 65557))
    tail = stream.read(min(encoded_size, 65557))
    end = tail.rfind(b"PK\x05\x06")
    while end >= 0:
        if end + 22 <= len(tail):
            values = struct.unpack_from("<4s4H2LH", tail, end)
            if end + 22 + values[7] == len(tail):
                break
        end = tail.rfind(b"PK\x05\x06", 0, end)
    if end < 0:
        raise EvidenceError("invalid ZIP end record")
    _, disk, directory_disk, disk_count, count, directory_size, offset, comment_size = values
    absolute_end = encoded_size - len(tail) + end
    if disk or directory_disk or disk_count != count:
        raise EvidenceError("split-volume ZIP archives are unsupported")
    if count == 65535 or directory_size == 0xffffffff or offset == 0xffffffff:
        if absolute_end < 20:
            raise EvidenceError("ZIP64 locator is missing")
        stream.seek(absolute_end - 20)
        signature, zip_disk, zip_offset, disks = struct.unpack("<4sLQL", stream.read(20))
        if signature != b"PK\x06\x07" or zip_disk or disks != 1 or zip_offset + 56 > encoded_size:
            raise EvidenceError("invalid or split-volume ZIP64 locator")
        stream.seek(zip_offset)
        header = stream.read(56)
        fields = struct.unpack("<4sQ2H2L4Q", header)
        if fields[0] != b"PK\x06\x06" or not 44 <= fields[1] <= metadata_limit or fields[4] or fields[5] or fields[6] != fields[7]:
            raise EvidenceError("invalid or oversized ZIP64 metadata")
        count, directory_size, offset = fields[7], fields[8], fields[9]
    if count > max_files or directory_size + comment_size > metadata_limit:
        raise EvidenceError("ZIP metadata or member count bound exceeded")
    if offset < 0 or offset + directory_size > absolute_end:
        raise EvidenceError("ZIP central directory lies outside archive")
    stream.seek(offset)
    consumed, actual_count = 0, 0
    while consumed < directory_size:
        header = stream.read(46)
        if len(header) != 46 or header[:4] != b"PK\x01\x02":
            raise EvidenceError("invalid ZIP central directory entry")
        name_size, extra_size, entry_comment = struct.unpack_from("<HHH", header, 28)
        length = 46 + name_size + extra_size + entry_comment
        consumed += length
        actual_count += 1
        if consumed > directory_size or actual_count > max_files:
            raise EvidenceError("ZIP actual member count or metadata bound exceeded")
        raw_name, extra = stream.read(name_size), stream.read(extra_size)
        if len(raw_name) != name_size or len(extra) != extra_size:
            raise EvidenceError("truncated ZIP member metadata")
        _zip_raw_names(raw_name, extra, struct.unpack_from("<H", header, 8)[0])
        stream.seek(entry_comment, os.SEEK_CUR)
    if actual_count != count:
        raise EvidenceError("ZIP declared member count does not match central records")
    stream.seek(0)


class _BoundedDecompression:
    def __init__(self, stream, maximum):
        self.stream, self.maximum, self.count = stream, maximum, 0

    def read(self, size=-1):
        if size < 0:
            size = CHUNK
        data = self.stream.read(min(size, self.maximum + 1 - self.count))
        self.count += len(data)
        if self.count > self.maximum:
            raise EvidenceError("archive decompression including metadata exceeds bound")
        return data


def _tar_info(metadata_limit, max_headers):
    class BoundedTarInfo(tarfile.TarInfo):
        def _proc_member(self, archive):
            archive._evidence_headers = getattr(archive, "_evidence_headers", 0) + 1
            if archive._evidence_headers > max_headers:
                raise EvidenceError("tar header count bound exceeded")
            metadata = self.type in (tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.SOLARIS_XHDTYPE,
                                    tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK)
            if metadata:
                archive._evidence_metadata = getattr(archive, "_evidence_metadata", 0) + self._block(self.size)
                if self.size < 0 or archive._evidence_metadata > metadata_limit:
                    raise EvidenceError("tar PAX/GNU metadata exceeds bound")
                # Header recursion is bounded separately from logical member count.
                archive._evidence_depth = getattr(archive, "_evidence_depth", 0) + 1
                if archive._evidence_depth > 32:
                    raise EvidenceError("tar metadata header chain exceeds bound")
            if self.type == tarfile.GNUTYPE_SPARSE:
                raise EvidenceError("sparse tar members are unsupported")
            try:
                result = super()._proc_member(archive)
                if result.sparse or any(k.startswith("GNU.sparse") for k in result.pax_headers):
                    raise EvidenceError("sparse tar members are unsupported")
                return result
            finally:
                if metadata:
                    archive._evidence_depth -= 1
    return BoundedTarInfo


def verify_pack(path, expected_hash, expected_size, expected_members=None, *,
                destination=None, max_bytes=128 * 1024 * 1024, max_files=10000,
                max_metadata_bytes=16 * 1024 * 1024, max_archive_bytes=None):
    """Validate every member, even when only one is requested. Extract by hash only."""
    _limit(max_bytes, "archive original byte bound", zero=True)
    _limit(max_files, "archive member count")
    _limit(max_metadata_bytes, "archive metadata bound")
    encoded_limit = max_bytes + max_metadata_bytes if max_archive_bytes is None else _limit(max_archive_bytes, "archive encoded byte bound", zero=True)
    if type(expected_size) is not int or expected_size < 0 or expected_size > encoded_limit:
        raise EvidenceError("encoded archive size exceeds configured bound")
    if hash_file(path) != (expected_hash, expected_size):
        raise EvidenceError("archive original bytes do not match identity")
    expected = None if expected_members is None else {x["member"]: x for x in expected_members}
    if expected_members is not None and len(expected) != len(expected_members):
        raise EvidenceError("duplicate expected archive member")
    seen, results, total, created_targets = set(), [], 0, []

    def discard_created():
        for target in created_targets:
            _parents(target)
            target.unlink(missing_ok=True)

    def consume(name, size, stream):
        nonlocal total
        safe_relative(name)
        if name in seen or len(seen) >= max_files:
            raise EvidenceError("duplicate member or archive member count limit")
        seen.add(name)
        if type(size) is not int or size < 0 or total + size > max_bytes:
            raise EvidenceError("archive decompression bound exceeded")
        digest, count = hashlib.sha256(), 0
        temporary = None
        if destination is not None:
            destination_path = _safe_directory(destination)
            temporary = destination_path / (".extract-" + hashlib.sha256(name.encode()).hexdigest())
            if temporary.exists() or temporary.is_symlink():
                raise EvidenceError("extraction temporary path already exists")
        try:
            output = _open_output(temporary) if temporary else None
            try:
                while block := stream.read(min(CHUNK, size - count + 1)):
                    count += len(block)
                    if count > size or total + count > max_bytes:
                        raise EvidenceError("archive member length/decompression mismatch")
                    digest.update(block)
                    if output:
                        output.write(block)
            finally:
                if output:
                    output.close()
            if count != size:
                raise EvidenceError("archive member truncated")
            item = {"member": name, "sha256": digest.hexdigest(), "size": count}
            if expected is not None and (name not in expected or any(expected[name][k] != item[k] for k in ("sha256", "size"))):
                raise EvidenceError("archive member does not match original identity")
            if temporary:
                target = destination_path / item["sha256"]
                if target.exists() or target.is_symlink():
                    if hash_file(target) != (item["sha256"], size):
                        raise EvidenceError("corrupt existing extracted object")
                    temporary.unlink()
                else:
                    _parents(target)
                    temporary.replace(target)
                    created_targets.append(target)
            results.append(item)
            total += count
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)

    source, descriptor, before = _open_regular(path)
    try:
        with ExitStack() as stack:
            raw = stack.enter_context(os.fdopen(descriptor, "rb", closefd=False))
            signature = raw.read(6)
            raw.seek(0)
            if signature[:2] == b"PK":
                _zip_preflight(raw, expected_size, max_files, max_metadata_bytes)
                archive = stack.enter_context(zipfile.ZipFile(raw))
                for info in archive.infolist():
                    # filename is normalized by ZipInfo on Windows. Its raw
                    # spelling must remain safe independently of that rewrite.
                    _zip_member_name(info.orig_filename)
                    mode = info.external_attr >> 16
                    if info.is_dir():
                        _zip_member_name(info.filename)
                        if info.filename in seen:
                            raise EvidenceError("duplicate directory member")
                        seen.add(info.filename)
                        if len(seen) > max_files:
                            raise EvidenceError("archive member count limit")
                        continue
                    if info.flag_bits & 1 or (stat.S_IFMT(mode) and not stat.S_ISREG(mode)):
                        raise EvidenceError("encrypted, linked or special archive member")
                    with archive.open(info) as stream:
                        consume(info.filename, info.file_size, stream)
            else:
                if signature[:2] == b"\x1f\x8b":
                    decompressed = stack.enter_context(gzip.GzipFile(fileobj=raw, mode="rb"))
                elif signature[:3] == b"BZh":
                    decompressed = stack.enter_context(bz2.BZ2File(raw, "rb"))
                elif signature == b"\xfd7zXZ\x00":
                    raise EvidenceError("xz archives require a bounded repack before adoption")
                else:
                    decompressed = raw
                bounded = _BoundedDecompression(decompressed, max_bytes + max_metadata_bytes)
                archive = stack.enter_context(tarfile.open(fileobj=bounded, mode="r|",
                                                          tarinfo=_tar_info(max_metadata_bytes, max_files * 3 + 32)))
                for info in archive:
                    if info.isdir():
                        safe_relative(info.name)
                        if info.name in seen or len(seen) >= max_files:
                            raise EvidenceError("duplicate directory or member count limit")
                        seen.add(info.name)
                        continue
                    if not info.isreg() or info.sparse:
                        raise EvidenceError("linked, sparse or special archive member")
                    with archive.extractfile(info) as stream:
                        consume(info.name, info.size, stream)
                # End-of-archive markers cannot conceal unbounded compressed tails.
                while bounded.read(CHUNK):
                    pass
            _verify_stable(source, descriptor, before)
    except (zipfile.BadZipFile, tarfile.TarError, EOFError, OSError, struct.error) as error:
        discard_created()
        raise EvidenceError("invalid archive: " + str(error)) from error
    except BaseException:
        discard_created()
        raise
    finally:
        os.close(descriptor)
    if expected is not None and set(expected) != {x["member"] for x in results}:
        discard_created()
        raise EvidenceError("archive member closure mismatch")
    if hash_file(path) != (expected_hash, expected_size):
        discard_created()
        raise EvidenceError("archive changed during validation")
    return {"sha256": expected_hash, "size": expected_size, "members": results,
            "original_bytes": total}
