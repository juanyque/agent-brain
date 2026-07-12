# Selection UI

Called from Step 2 of the workflow. Never act on any finding until the user has
explicitly selected it here.

Findings are always presented **grouped by `target`** (logical object key). Within
each group, new findings appear before pending ones. Freshness indicators:

- `[NEW]` — found in this session (`status: new`)
- `[PENDING · Apr 21 · ×2]` — loaded from backlog, last seen Apr 21, detected twice
- `[STALE? · Apr 8 · ×1]` — `last_seen` is more than 7 days ago; may no longer apply

Example grouped presentation:

```
━━━ your-project / boyscout-skill ━━━━━━━━━━━━━━━━━━━
1. [XS][skill-gap] allowed-tools missing gh for PR guard   [NEW · ×1]
2. [XS][skill-gap] summary report variant missing          [PENDING · Apr 21 · ×2]

━━━ your-project / card-simulator-claude-plugin ━━━━━
3. [XS][docs-gap]  cs_smoke_full missing from ZSH table    [STALE? · Apr 8 · ×1]
```

When the user selects multiple findings from the same target, note: "Items X and Y
share target `<repo> / <component>` — they will be fixed together in one PR."

## Preferred: fzf multi-select

Write each finding's full details to its own numbered temp file, then verify
that the backlog is small enough for fzf (≤ 5 findings), TTY is available,
and `fzf` is installed before launching with a preview pane.

**Temp file format:** First line must be the display line (used as the fzf
list item) — format: `N. [effort][type] one-line-summary [freshness]`.
Remaining lines hold the full detail shown in the preview pane, including
`target`, `location`, `detected`, `last_seen`, and `times_seen`.

Number findings globally (1, 2, 3, …) across all groups. Group separators
(`━━━ <target> ━━━`) are written to a header file
(`/tmp/boyscout/groups.txt`) for the fallback display but are not part of
the individual N.txt files.

```bash
rm -rf /tmp/boyscout
mkdir -p /tmp/boyscout
# For each finding N, write /tmp/boyscout/N.txt with full details
```

```bash
if { true < /dev/tty; } 2>/dev/null; then
  if command -v fzf >/dev/null 2>&1; then
    ls /tmp/boyscout/[0-9]*.txt | \
      xargs -I{} basename {} .txt | \
      sort -n | \
      xargs -I{} sh -c 'echo "{}. $(head -1 /tmp/boyscout/{}.txt)"' | \
      fzf --multi \
          --preview 'num=$(echo {} | cut -d. -f1 | tr -d " "); cat /tmp/boyscout/$num.txt 2>/dev/null || echo "No details available"' \
          --preview-window 'right:55%:wrap' \
          --header 'SPACE: select | ENTER: confirm | Arrows: navigate (preview updates automatically)' \
          --prompt 'Select tasks to tackle > '
          # In /boyscout clean mode, override to: --prompt 'Select findings to remove from the backlog > '
  else
    echo "fzf not available" >&2
    false
  fi
else
  false  # no controlling terminal or fzf unavailable → AskUserQuestion fallback
fi
```

## Fallback: AskUserQuestion

If `count(all_findings) > 5`, `/dev/tty` is not accessible, or `fzf` fails (not installed or non-zero exit), fall back to
`AskUserQuestion` with a numbered list grouped by target:

```
Found N improvement opportunities:

━━━ your-project / boyscout-skill ━━━━━━━━━━━━━━━━━━━━━━━━
1. [XS][skill-gap]  user-skill/boyscout/SKILL.md — allowed-tools missing gh   [NEW · ×1]
2. [XS][skill-gap]  user-skill/boyscout/SKILL.md — summary report variant     [PENDING · Apr 21 · ×2]

━━━ all-the-things / card-simulator-docs ━━━━━━━━━━━━━━━━━━━━━━━━
3. [S] [docs-gap]   tooling.md — Bruno collection tree stale                  [NEW · ×1]
4. [S] [missing-test] orders/ — No integration tests for cancellation flow    [STALE? · Apr 8 · ×1]

Type the numbers to tackle (e.g. "1 3"), or type "d 2" for details on item 2.
Selecting items from the same target group → single PR for that group.
```

If the user types `d N`, show the full detail for that finding (including target, detected, last_seen, times_seen) and re-ask.
Repeat until they confirm a selection.
