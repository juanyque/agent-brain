from __future__ import annotations

import io
import os
import tarfile
from pathlib import Path

from evidence_git import git_admin_paths, scan_git_admin_path
from evidence_json import ContractError, create_bytes, decode_path, read_bytes_no_follow


def create_git_reconstruction_archive(root: Path, archive_path: Path) -> bytes:
    paths = git_admin_paths(root.resolve())
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        if paths is not None:
            git_dir = paths[0]
            entries = scan_git_admin_path(git_dir)
            root_info = tarfile.TarInfo(".git")
            root_info.type = tarfile.DIRTYPE
            root_info.mode = 0o700
            root_info.uid = 0
            root_info.gid = 0
            root_info.uname = ""
            root_info.gname = ""
            root_info.mtime = 0
            archive.addfile(root_info)
            for entry in entries:
                name = ".git/" + os.fsdecode(decode_path(entry["path_b64"]))
                info = tarfile.TarInfo(name)
                info.mode = int(entry["mode"])
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                info.mtime = 0
                kind = entry["type"]
                if kind == "directory":
                    info.type = tarfile.DIRTYPE
                    archive.addfile(info)
                elif kind == "symlink":
                    info.type = tarfile.SYMTYPE
                    info.linkname = os.fsdecode(decode_path(entry["target_b64"]))
                    archive.addfile(info)
                elif kind == "file":
                    data = read_bytes_no_follow(git_dir / os.fsdecode(decode_path(entry["path_b64"])))
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))
                else:
                    raise ContractError("unknown Git archive entry")
    data = output.getvalue()
    create_bytes(archive_path, data)
    return data


def reconstruct_git_archive(archive_path: Path, output_root: Path) -> None:
    reconstruct_git_archive_bytes(read_bytes_no_follow(archive_path), output_root)


def reconstruct_git_archive_bytes(data: bytes, output_root: Path) -> None:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        for member in archive.getmembers():
            name = member.name
            if name != ".git" and not name.startswith(".git/"):
                raise ContractError("Git reconstruction archive contains unsafe member")
            relative = name.encode("utf-8")
            if b".." in relative.split(b"/") or name.startswith("/"):
                raise ContractError("Git reconstruction archive contains unsafe path")
            target = output_root / name
            if member.isdir():
                target.mkdir(mode=member.mode, exist_ok=False)
            elif member.issym():
                os.symlink(member.linkname, target)
            elif member.isfile():
                stream = archive.extractfile(member)
                if stream is None:
                    raise ContractError("Git reconstruction archive file is unreadable")
                descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, member.mode)
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(stream.read())
            else:
                raise ContractError("Git reconstruction archive contains unsupported member")
