# Link rules

Use this rule whenever adding or correcting internal Obsidian links.

## Internal note links

When referencing another note inside the brain, use Obsidian wiki links:

```markdown
[[Note title]]
```

Do not use filesystem paths for brain notes:

```markdown
WIP/Example project.md
```

Use filesystem paths only when referencing files outside the brain or when the path itself is the subject.

## Daily note links

When referencing another daily note, use Obsidian wiki links:

```markdown
[[YYYY-MM-DD]]
```

Example:

```markdown
Backups — scripts created and tested (see [[2026-05-07]])
```

Do not leave bare daily-note dates when the intent is to reference the note.
