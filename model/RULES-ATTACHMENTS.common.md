# Attachment rules

Use this rule when creating, moving, auditing, repairing, or quarantining attachments.

## Source of truth

This file is the canonical operational policy for attachment ownership and relocation.

- `BRAIN.md` defines the conceptual folder model and still names `ATTACHMENTS/` and `QUARANTINE/ATTACHMENTS/`.
- `AGENTS.md` only routes attachment work to this rule.
- `RULES-FILE-NAMING.common.md` owns filename identity and basename-collision policy.
- Attachment audit and canvas repair tooling stay dry-run by default and require explicit approval before applying moves or rewrites.

## Ownership and relocation

- Attachments should move together with the notes they clearly belong to whenever those notes are reorganized.
- Every attachment belongs directly in the local `ATTACHMENTS/` directory beside the folder containing its owning note. This is the creation and organization invariant even when Obsidian can resolve the link from another location.
- `ATTACHMENTS/` directories are flat and file-only. Never create project, topic, document, extraction, or other organizational subdirectories inside them. Put that information structure in the brain first, then place each file in the `ATTACHMENTS/` directory beside the structure that owns it.
- Example: an attachment used only by `WIP/project/documents/note.md` belongs at `WIP/project/documents/ATTACHMENTS/<filename>`, not at `WIP/ATTACHMENTS/project/<filename>` or `WIP/project/ATTACHMENTS/documents/<filename>`.
- If attachment ownership is already clear while reading and moving a note, move the attachment at the same time as the note.
- If attachment ownership is not resolved during note reorganization, defer that case to deterministic maintenance tooling instead of guessing manually.
- Reorganizing a note should include checking its linked attachments and moving them with traceability when ownership is clear.
- Never move an attachment that an active process still reads or writes. Restrict the audit scope or defer the relocation until that process records a handoff and releases the path.
- Never delete attachments automatically during reorganization.
- Potential orphaned attachments should be moved to `QUARANTINE/ATTACHMENTS/` for manual review rather than deleted.
- Conflicts such as duplicate filenames, one attachment referenced from multiple notes in different locations, or ambiguous ownership should be reported and left unresolved until reviewed explicitly.
- After a folder has been fully reorganized, review any remaining `ATTACHMENTS/` contents there to determine whether they are still valid local attachments, were missed during migration, or are potential orphans.

## Creation convention

- Create or extract attachments directly into the owning note folder's `ATTACHMENTS/` directory. Create the owning information structure before extracting files; never encode that structure below `ATTACHMENTS/`.

## Quarantine destination

- `QUARANTINE/ATTACHMENTS/` is the destination for potential orphaned or ambiguous attachments found during reorganization or maintenance.

## Tooling

- Use `attachments_audit.py` to audit every file recursively below `ATTACHMENTS/` folders under a chosen scope. Nested files are non-conforming defensive inputs; after the required apply-mode confirmation, the tool flattens safe cases into the owning note folder's local `ATTACHMENTS/` with `git mv` under the bounded standing authorization in `AGENTS.common.md`.
- Choose the narrowest scope that covers the completed information structure. Exclude or defer any subtree reserved by an active process.
- Use `canvas_path_repair.py` to audit `.canvas` file-node paths and optionally repair only uniquely resolvable broken paths.
- Run the dry-run command first, inspect machine-readable or console output, then ask for explicit approval before any `--apply` invocation.
