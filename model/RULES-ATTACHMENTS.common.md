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
- Preferred convention: attachments live near their owning notes, typically in local `ATTACHMENTS/` folders controlled by Obsidian settings and cleanup scripts. This setting is primarily an organizational rule for creation, not a hard requirement for later link resolution.
- If attachment ownership is already clear while reading and moving a note, move the attachment at the same time as the note.
- If attachment ownership is not resolved during note reorganization, defer that case to deterministic maintenance tooling instead of guessing manually.
- Reorganizing a note should include checking its linked attachments and moving them with traceability when ownership is clear.
- Never delete attachments automatically during reorganization.
- Potential orphaned attachments should be moved to `QUARANTINE/ATTACHMENTS/` for manual review rather than deleted.
- Conflicts such as duplicate filenames, one attachment referenced from multiple notes in different locations, or ambiguous ownership should be reported and left unresolved until reviewed explicitly.
- After a folder has been fully reorganized, review any remaining `ATTACHMENTS/` contents there to determine whether they are still valid local attachments, were missed during migration, or are potential orphans.

## Creation convention

- Attachments should preferably be created near the current note or in a predictable local `ATTACHMENTS/` folder, then maintained by attachment ownership rules.

## Quarantine destination

- `QUARANTINE/ATTACHMENTS/` is the destination for potential orphaned or ambiguous attachments found during reorganization or maintenance.

## Tooling

- Use `attachments_audit.py` to audit `ATTACHMENTS/` folders under a chosen scope and, after the required apply-mode confirmation, relocate safe cases with `git mv` under the bounded standing authorization in `AGENTS.common.md`.
- Use `canvas_path_repair.py` to audit `.canvas` file-node paths and optionally repair only uniquely resolvable broken paths.
- Run the dry-run command first, inspect machine-readable or console output, then ask for explicit approval before any `--apply` invocation.
