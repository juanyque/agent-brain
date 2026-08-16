from pathlib import Path


RUNTIME_CONFIGS = {
    "claude": {
        "local_dir": Path("~/.claude"),
        "agents_subdir": "CLAUDE",
        "mappings": [
            ("CLAUDE.runtime.claude.md", "CLAUDE.md"),
            ("settings.json", "settings.json"),
            ("memory", "memory"),
        ],
        "skills_dir": Path("~/.claude/skills"),
    },
    "opencode": {
        "local_dir": Path("~/.config/opencode"),
        "agents_subdir": "OPENCODE",
        "mappings": [
            ("AGENTS.runtime.opencode.md", "AGENTS.md"),
            ("opencode.json", "opencode.json"),
            ("oh-my-openagent.json", "oh-my-openagent.json"),
        ],
        "skills_dir": Path("~/.agents/skills"),
    },
    "agents": {
        "local_dir": Path("~/.agents"),
        "agents_subdir": "AGENTS",
        "mappings": [("AGENTS.runtime.agents.md", "AGENTS.md")],
        "skills_dir": Path("~/.agents/skills"),
    },
    "codex": {
        "local_dir": Path("~/.codex"),
        "agents_subdir": "CODEX",
        "mappings": [
            ("AGENTS.runtime.codex.md", "AGENTS.md"),
            ("config.toml", "config.toml"),
        ],
        "skills_dir": Path("~/.agents/skills"),
        "private_targets": {"config.toml"},
    },
    "antigravity": {
        "local_dir": Path("~/.gemini/antigravity-cli"),
        "agents_subdir": "ANTIGRAVITY",
        "mappings": [],
        "skills_dir": Path("~/.gemini/antigravity-cli/skills"),
    },
}

RUNTIME_LABELS = {
    "claude": "Claude",
    "opencode": "OpenCode",
    "agents": "Agents",
    "codex": "Codex",
    "antigravity": "Antigravity CLI",
}

RUNTIME_HOMES = [Path("~/.agents"), Path("~/.claude"), Path("~/.codex")]
INBOX_RUNTIME_DIR_NAME = "INBOX/_RUNTIME"
