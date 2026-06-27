"""Bash command intent classifier (plan section 11).

A single command can map to multiple intents — e.g. an ssh line that runs
``git pull && docker compose up -d`` is REMOTE + GIT + DEPLOY. Callers get a
list back so dashboards can show every relevant badge.

The classifier is intentionally regex-based and conservative: complex one
liners fall through to UNKNOWN rather than guessing. Coverage of high-frequency
commands matters more than edge-case recall (plan risk 2).
"""

from __future__ import annotations

import re
from typing import List, Tuple

# Intent label enumeration (plan 11.1). Order only matters for stable display.
INTENT_LABELS: Tuple[str, ...] = (
    "TEST",
    "BUILD",
    "DEPLOY",
    "REMOTE",
    "DEBUG",
    "FILE_OP",
    "GIT",
    "INSTALL",
    "DB",
    "NETWORK",
    "SECURITY",
    "UNKNOWN",
)

# Each pattern compiled once at import. Keep patterns anchored to word
# boundaries so e.g. "scp" does not match inside "script".
_COMMAND_PATTERNS = [
    ("TEST", [
        r"\bpytest\b",
        r"\bjest\b",
        r"\bvitest\b",
        r"\bmocha\b",
        r"\bnpm\s+test\b",
        r"\bnpx\s+pytest\b",
        r"\bpnpm\s+test\b",
        r"\byarn\s+test\b",
        r"\bcargo\s+test\b",
        r"\bgo\s+test\b",
        r"\bmvn\s+test\b",
        r"\bgradle\s+test\b",
        r"\btox\b",
        r"\brspec\b",
        r"\bunittest\b",
    ]),
    ("BUILD", [
        r"\bnpm\s+run\s+build\b",
        r"\bnpm\s+run\s+(?:ci:)?build\b",
        r"\bpnpm\s+build\b",
        r"\bpnpm\s+run\s+build\b",
        r"\byarn\s+build\b",
        r"\bmake\b(?:\s+build)?",
        r"\bdocker\s+build\b",
        r"\bpodman\s+build\b",
        r"\bcargo\s+build\b",
        r"\bgo\s+build\b",
        r"\btsc\b",
        r"\bwebpack\b",
        r"\bvite\s+build\b",
        r"\bmvn\s+(?:package|install)\b",
        r"\bgradle\s+(?:build|assemble)\b",
    ]),
    ("DEPLOY", [
        r"\bsystemctl\s+(?:restart|reload|start|stop|enable|disable)\b",
        r"\bdocker\s+compose\s+up\b",
        r"\bdocker-compose\s+up\b",
        r"\bdocker\s+stack\s+deploy\b",
        r"\bdocker\s+service\s+(?:create|update)\b",
        r"\bpm2\s+(?:restart|reload|start)\b",
        r"\bkubectl\s+(?:apply|rollout|restart|create|replace)\b",
        r"\bhelm\s+(?:install|upgrade)\b",
        r"\bnginx\s+-s\s+(?:reload|stop|reopen)\b",
        r"\bsupervisorctl\s+(?:restart|reload|reread|update)\b",
        r"\bansible-playbook\b",
        r"\bterraform\s+apply\b",
        r"\bcap\s+deploy\b",
        r"\bminikube\s+start\b",
    ]),
    ("REMOTE", [
        # require ssh/scp/rsync to be actual commands, not substrings of paths
        r"(?:^|[\s;&|`(])ssh(?:\s|$)",
        r"(?:^|[\s;&|`(])scp(?:\s|$)",
        r"(?:^|[\s;&|`(])rsync(?:\s|$)",
        r"\bmosh\b",
    ]),
    ("DEBUG", [
        r"\btail\s+-",
        r"\bhead\s+-",
        r"\bless\b",
        r"\bmore\b",
        r"\bjournalctl\b",
        r"\bdocker\s+logs\b",
        r"\bpodman\s+logs\b",
        r"\bkubectl\s+logs\b",
        r"\b(?:grep|rg|ag|ack)\b",
        r"\blsof\b",
        r"\bstrace\b",
        r"\bltrace\b",
        r"\bgdb\b",
        r"\blldb\b",
        r"\bps\s+",
        r"\bnetstat\b",
        r"\bss\s+",
        r"\bhtop\b",
        r"\btop\b",
        r"\biostat\b",
        r"\bdmesg\b",
        r"\bvmstat\b",
    ]),
    ("FILE_OP", [
        r"\bsed\s+-i\b",
        r"\bawk\s+-i\b",
        r"\bcat\s*>",
        r"\bcat\s+>>",
        r"\btee\b",
        r"\bmv\b",
        r"\bcp\b",
        r"\brm\s+-",
        r"\bmkdir\s+-",
        r"\btouch\b",
        r"\bchmod\b",
        r"\bchown\b",
        r"\binstall\s+-m\b",
    ]),
    ("GIT", [
        r"\bgit\s+status\b",
        r"\bgit\s+diff\b",
        r"\bgit\s+add\b",
        r"\bgit\s+commit\b",
        r"\bgit\s+pull\b",
        r"\bgit\s+push\b",
        r"\bgit\s+checkout\b",
        r"\bgit\s+(?:merge|rebase|cherry-pick)\b",
        r"\bgit\s+stash\b",
        r"\bgit\s+log\b",
        r"\bgit\s+show\b",
        r"\bgit\s+restore\b",
    ]),
    ("INSTALL", [
        r"\bnpm\s+install\b",
        r"\bnpm\s+i\b",
        r"\bnpm\s+ci\b",
        r"\bpnpm\s+install\b",
        r"\bpnpm\s+add\b",
        r"\byarn\s+(?:add|install)\b",
        r"\bpip\s+install\b",
        r"\bpip3\s+install\b",
        r"\buv\s+(?:add|install|pip)\b",
        r"\bpoetry\s+(?:add|install)\b",
        r"\bapt(?:-get)?\s+install\b",
        r"\baptitude\s+install\b",
        r"\bbrew\s+install\b",
        r"\bpacman\s+-S\b",
        r"\bdnf\s+install\b",
        r"\byum\s+install\b",
        r"\bzypper\s+install\b",
        r"\bcargo\s+add\b",
        r"\bgo\s+(?:get|install)\b",
        r"\bmvn\s+install\b",
        r"\bgradle\s+install\b",
    ]),
    ("DB", [
        r"\bprisma\s+migrate\b",
        r"\bprisma\s+db\s+push\b",
        r"\balembic\b",
        r"\bknex\b",
        r"\bmysql\b",
        r"\bpsql\b",
        r"\bsqlite3\b",
        r"\bdiesel\b",
        r"\bsequel\b",
        r"\brails\s+db:migrate\b",
        r"\bmanage\.py\s+migrate\b",
        r"\bmongosh\b",
        r"\bredis-cli\b",
    ]),
    ("NETWORK", [
        r"\bcurl\b",
        r"\bwget\b",
        r"\bping\b",
        r"\bnc\b",
        r"\bnetcat\b",
        r"\bdig\b",
        r"\bnslookup\b",
        r"\bhost\b",
        r"\btraceroute\b",
        r"\btracepath\b",
        r"\bipconfig\b",
        r"\bifconfig\b",
        r"\bip\s+(?:addr|route|link)\b",
    ]),
    ("SECURITY", [
        r"\bssh-keygen\b",
        r"\bcertbot\b",
        r"\bopenssl\b",
        r"\bgpg\b",
        r"\bchmod\s+[0-7]{3,4}\b",
        r"\bchown\b",
        r"\bchattr\b",
        r"\bsetenforce\b",
        r"\bapparmor\b",
        r"\bsestatus\b",
    ]),
]

# Pre-compile for speed (extractor may classify thousands of commands).
_COMPILED = [
    (label, [re.compile(p, re.IGNORECASE) for p in patterns])
    for label, patterns in _COMMAND_PATTERNS
]

# Commands that almost always indicate a remote file mutation. These feed the
# remote file footprint extractor (plan 9.2). Listed separately from intents
# because they carry path information.
REMOTE_FILE_PATTERNS = [
    # sed -i ... path   (allow quoted s/../../ expressions)
    (re.compile(r"\bsed\s+-i(?:\s+(?:-E|--regexp-extended))?[^|;`]*?\b(/[\S]+|~/\S+)\s*$"), "ssh_sed_i"),
    # cat > path        or cat >> path
    (re.compile(r"\bcat\s>>(?:>?)\s*(\S+)"), "ssh_cat_redirect"),
    # tee path          or tee -a path
    (re.compile(r"\btee\s+(?:-a\s+)?(\S+)"), "ssh_tee"),
    # scp src ... dst   (last token usually the destination)
    (re.compile(r"\bscp\s+.*?\s+(\S+)\s*$"), "scp_target"),
]


def classify_command(command: str) -> List[str]:
    """Return every intent label the command matches.

    Always non-empty — bare / unrecognised commands yield ``["UNKNOWN"]``.
    A typical ssh deploy line yields ``["REMOTE", "GIT", "DEPLOY", "DEBUG"]``.
    """
    text = str(command or "")
    if not text.strip():
        return ["UNKNOWN"]
    matched: List[str] = []
    for label, patterns in _COMPILED:
        for pat in patterns:
            if pat.search(text):
                matched.append(label)
                break
    if not matched:
        return ["UNKNOWN"]
    return matched


def extract_remote_file_paths(command: str) -> List[str]:
    """Best-effort extraction of file paths mutated over ssh (plan 9.2).

    Returned paths are absolute or ``~``-relative — the patterns intentionally
    ignore bare filenames (too noisy).
    """
    text = str(command or "")
    paths: List[str] = []
    for pat, _name in REMOTE_FILE_PATTERNS:
        for m in pat.finditer(text):
            try:
                groups = [g for g in m.groups() if g]
            except re.error:
                continue
            for g in groups:
                cleaned = g.strip().strip("'\"")
                if not cleaned:
                    continue
                # keep only absolute-ish or home-relative paths
                if cleaned.startswith("/") or cleaned.startswith("~/") or cleaned.startswith("~"):
                    if cleaned not in paths:
                        paths.append(cleaned)
    return paths
