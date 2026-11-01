"""Read the XML members of an untrusted zip archive without ever extracting it.

Nothing is written to disk, so zip-slip cannot write anywhere; names that try it are still
rejected, because an archive that contains them is not a GII download. Limits (all explicit and
parameters of :class:`ZipLimits`): member count, uncompressed size per member and in total,
compression ratio (zip bombs) and a bounded read that does not trust the header.
"""

import stat
import zipfile
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from pruefstand.ingest.gii.errors import UnsafeArchiveError

_MIB = 1024 * 1024
_READ_CHUNK = 1 << 16


@dataclass(frozen=True)
class ZipLimits:
    """Safety limits for one archive.

    The defaults are far above the real GII files (the largest XML is about 2.5 MB and
    compresses about 5:1).

    Attributes:
        max_members: Entries in the archive (the GII zips hold one XML plus images).
        max_member_bytes: Uncompressed bytes of one member.
        max_total_bytes: Declared uncompressed bytes of all members together.
        max_ratio: Uncompressed / compressed bytes of one member.
    """

    max_members: int = 1000
    max_member_bytes: int = 64 * _MIB
    max_total_bytes: int = 256 * _MIB
    max_ratio: int = 200


def _check_name(name: str) -> None:
    path = PurePosixPath(name)
    bad = (
        not name
        or "\x00" in name
        or "\\" in name
        or path.is_absolute()
        or ".." in path.parts
        or (len(name) > 1 and name[1] == ":")
    )
    if bad:
        msg = f"unsafe member name {name!r}"
        raise UnsafeArchiveError(msg)


def check_member(info: zipfile.ZipInfo, limits: ZipLimits) -> None:
    """Validate one member's header: name, symlink, encryption, declared size and ratio.

    Raises:
        UnsafeArchiveError: The member breaks a rule or limit.
    """
    _check_name(info.filename)
    mode = info.external_attr >> 16
    if info.create_system == 3 and stat.S_ISLNK(mode):
        msg = f"symlink member {info.filename!r}"
        raise UnsafeArchiveError(msg)
    if info.flag_bits & 0x1:
        msg = f"encrypted member {info.filename!r}"
        raise UnsafeArchiveError(msg)
    if info.file_size > limits.max_member_bytes:
        msg = f"member {info.filename!r} exceeds the size limit ({limits.max_member_bytes} bytes)"
        raise UnsafeArchiveError(msg)
    if info.file_size > limits.max_ratio * max(info.compress_size, 1):
        msg = f"member {info.filename!r} exceeds the compression ratio limit ({limits.max_ratio})"
        raise UnsafeArchiveError(msg)


def read_bounded(zf: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    """Read one member, never more than ``limit`` bytes, whatever its header claims.

    Args:
        zf: Open archive.
        info: Member to read.
        limit: Largest allowed uncompressed size in bytes.

    Returns:
        The member's bytes.

    Raises:
        UnsafeArchiveError: The member is larger than ``limit`` or corrupt (CRC, deflate).
    """
    chunks: list[bytes] = []
    size = 0
    try:
        with zf.open(info) as handle:
            while chunk := handle.read(_READ_CHUNK):
                size += len(chunk)
                if size > limit:
                    msg = f"member {info.filename!r} exceeds the size limit ({limit} bytes)"
                    raise UnsafeArchiveError(msg)
                chunks.append(chunk)
    except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError) as err:
        msg = f"corrupt member {info.filename!r}: {err}"
        raise UnsafeArchiveError(msg) from err
    return b"".join(chunks)


def read_xml_members(path: Path, limits: ZipLimits | None = None) -> Iterator[tuple[str, bytes]]:
    """Yield ``(name, bytes)`` of every ``*.xml`` member, sorted by name; ignore all others.

    The whole archive is validated before the first member is read.

    Args:
        path: The ``xml.zip`` file.
        limits: Safety limits (defaults: :class:`ZipLimits`).

    Yields:
        One tuple per XML member.

    Raises:
        UnsafeArchiveError: Not a zip, or a member breaks a rule or limit.
    """
    limits = limits or ZipLimits()
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as err:
        msg = f"not a valid zip file: {err}"
        raise UnsafeArchiveError(msg) from err
    with archive:
        infos = archive.infolist()
        if len(infos) > limits.max_members:
            msg = f"too many members ({len(infos)} > {limits.max_members})"
            raise UnsafeArchiveError(msg)
        for info in infos:
            check_member(info, limits)
        if sum(i.file_size for i in infos) > limits.max_total_bytes:
            msg = f"total uncompressed size exceeds {limits.max_total_bytes} bytes"
            raise UnsafeArchiveError(msg)
        for info in sorted(infos, key=lambda i: i.filename):
            if not info.is_dir() and info.filename.lower().endswith(".xml"):
                yield info.filename, read_bounded(archive, info, limits.max_member_bytes)
