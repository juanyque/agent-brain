# session_bootstrap.py

## Purpose
- Inspect the vault state before starting a fresh LLM session.
- Print a ready-to-send kickoff prompt so the first user message can trigger the expected session-start protocol.

## Why this exists
- The LLM does not self-start just by opening a new session window.
- It only begins protocol work after receiving a message.
- This helper automates the *pre-flight inspection* so the first message can be informed and consistent.

## What it checks
- current date
- whether today's daily note already exists
- the latest daily note found in `JOURNAL/`
- existing session notes in `WIP/SESSIONS/`

## Usage
```bash
python3 ~/.agents/skills/brain/scripts/session_bootstrap.py --brain-root .
```

## Output
- a compact vault-state summary
- a recommended kickoff prompt to send as the first message in a clean session

## Limitations
- It does not create notes or session files by itself.
- It does not inject a message into the LLM session.
- If the agent runtime later supports passing an initial prompt on startup, this script could be extended or wrapped to do that automatically.
