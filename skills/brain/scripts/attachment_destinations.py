"""Flat-destination policy for attachment producers.

A valid attachment destination is a direct file child of an exact
``ATTACHMENTS/`` directory: ``QUARANTINE/ATTACHMENTS/orphan.pdf`` is valid,
nested descendants and paths outside every ``ATTACHMENTS/`` are not. This
module is the shared preflight the attachment rules name for every script
that creates, copies, extracts, or moves attachments. It is a structural
safeguard, not protection against symlink races.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

ATTACHMENTS_DIR_NAME = "ATTACHMENTS"


class AttachmentDestinationError(ValueError):
    pass


def collision_key(resolved_destination: Path) -> tuple[tuple[str, ...], str]:
    """Filesystem-equivalence key for a resolved destination.

    Darwin filesystems match names case-insensitively and Unicode-
    composition-insensitively, so two differently spelled paths (in any
    component, not just the basename) can be the same entry. Normalizing
    every part with NFC + casefold collides more than the filesystem does,
    which is the safe direction for a preflight.
    """
    parent_parts = tuple(
        unicodedata.normalize("NFC", part).casefold()
        for part in resolved_destination.parent.parts
    )
    return (
        parent_parts,
        unicodedata.normalize("NFC", resolved_destination.name).casefold(),
    )


def flat_attachment_shape(path: str | Path) -> bool:
    """Shape-only check: parent is the single ATTACHMENTS component.

    Purely lexical: no path resolution and no filesystem entry inspection,
    so a symlinked ``ATTACHMENTS/`` directory does not change the verdict.
    Fits locations that are merely reported (nothing will be written
    through them); producers writing files must use
    :func:`require_flat_attachment_destination` instead.
    """
    try:
        candidate = _expanded(path)
    except AttachmentDestinationError:
        return False
    parts = candidate.parts
    if ".." in parts or len(parts) < 2 or parts[-2] != ATTACHMENTS_DIR_NAME:
        return False
    return sum(part == ATTACHMENTS_DIR_NAME for part in parts) == 1


def _expanded(path: str | Path) -> Path:
    try:
        return Path(path).expanduser()
    except (RuntimeError, OSError) as error:
        raise AttachmentDestinationError(
            f"Attachment destination could not be expanded: {path} ({error})"
        ) from error


def _normalized(path: str | Path) -> Path:
    candidate = _expanded(path)
    if ".." in candidate.parts:
        raise AttachmentDestinationError(
            f"Attachment destination must not contain '..' components: {path}"
        )
    try:
        return candidate.parent.resolve(strict=False) / candidate.name
    except (RuntimeError, OSError) as error:
        raise AttachmentDestinationError(
            f"Attachment destination could not be normalized: {path} ({error})"
        ) from error


def is_flat_attachment_destination(
    path: str | Path,
    *,
    brain_root: str | Path | None = None,
) -> bool:
    try:
        require_flat_attachment_destination(path, brain_root=brain_root)
    except AttachmentDestinationError:
        return False
    return True


def require_flat_attachment_destination(
    path: str | Path,
    *,
    brain_root: str | Path | None = None,
) -> Path:
    """Validate an attachment destination and return the parent-resolved path.

    Accepts only a file whose immediate parent is a directory named exactly
    ``ATTACHMENTS`` (case-sensitive) that is the only ``ATTACHMENTS``
    component in the whole path. Symlink prefixes are resolved, but the
    final component is not: a destination that already exists as a symlink
    (even dangling, or pointing outside the brain) is rejected outright,
    because a producer would write through it. With ``brain_root``, the
    resolved destination must stay inside that root.
    """
    leaf = _expanded(path)
    try:
        leaf_is_symlink = leaf.is_symlink()
    except OSError as error:
        raise AttachmentDestinationError(
            f"Attachment destination could not be inspected: {path} ({error})"
        ) from error
    if leaf_is_symlink:
        raise AttachmentDestinationError(
            f"Attachment destination is a symlink: {path}"
        )
    resolved = _normalized(path)
    if not resolved.is_absolute():
        raise AttachmentDestinationError(
            f"Attachment destination must resolve to an absolute path: {path}"
        )
    if resolved.parent.name != ATTACHMENTS_DIR_NAME:
        raise AttachmentDestinationError(
            f"Attachment destination must be a direct child of an "
            f"{ATTACHMENTS_DIR_NAME}/ directory: {path}"
        )
    if sum(part == ATTACHMENTS_DIR_NAME for part in resolved.parts) != 1:
        raise AttachmentDestinationError(
            f"Attachment destination must contain exactly one "
            f"{ATTACHMENTS_DIR_NAME} component: {path}"
        )
    if resolved.parent.parent == resolved.parent:
        raise AttachmentDestinationError(
            f"Attachment destination must be a file inside the brain: {path}"
        )
    if brain_root is not None:
        try:
            root = Path(brain_root).expanduser().resolve(strict=False)
        except (RuntimeError, OSError) as error:
            raise AttachmentDestinationError(
                f"Brain root could not be resolved: {brain_root} ({error})"
            ) from error
        if not resolved.is_relative_to(root) or resolved == root:
            raise AttachmentDestinationError(
                f"Attachment destination must stay inside brain root "
                f"{root}: {path}"
            )
    return resolved
