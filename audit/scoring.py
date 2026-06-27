"""Value / friction / outcome scoring (plan sections 10, 14, 15).

All formulas are deterministic and cheap. They are *signals*, not scientific
KPIs (plan 15.5) — the UI deliberately labels them "Value Signal" etc.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

# Intent labels that count towards value vs friction.
VALUE_INTENTS = ("DEPLOY", "TEST", "GIT", "INSTALL")
ACTION_INTENTS = ("BUILD", "FILE_OP", "REMOTE", "DB", "NETWORK", "SECURITY", "DEBUG")

# Tool names (lowercased) that mutate files locally (plan 9.1).
LOCAL_FILE_TOOLS = frozenset({"edit", "write", "multiedit", "notebook", "create_file", "str_replace_editor", "apply_patch"})
# Tools that carry a shell command we can classify.
SHELL_COMMAND_TOOLS = frozenset({"bash", "shell", "shell_command", "execute_bash", "run_command", "powershell", "cmd"})


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    if value < low:
        return low
    if value > high:
        return high
    return value


# ---------------------------------------------------------------------------
# Ghost modification weighting (plan 10).
# ---------------------------------------------------------------------------

def apply_ghost_modification_weights(file_mutation_stats: Dict[str, Dict]) -> None:
    """Discount ``net_value_weight`` for files touched many times on failed runs.

    Mutates the stats dict in place. Files that keep getting edited while the
    session errored / was interrupted get discounted so value_score does not
    credit churn that produced no net delivery.
    """
    for path, stats in file_mutation_stats.items():
        edit_count = int(stats.get("edit_count", 0) or 0)
        write_count = int(stats.get("write_count", 0) or 0)
        total = edit_count + write_count
        outcome = str(stats.get("final_outcome") or "unknown")
        weight = 1.0
        if outcome in ("errored", "interrupted"):
            if total > 5:
                weight = 0.2
            elif total > 3:
                weight = 0.3
            elif total > 1:
                weight = 0.5
        elif outcome in ("incomplete", "partially_completed"):
            if total > 5:
                weight = 0.5
            elif total > 3:
                weight = 0.7
        stats["net_value_weight"] = round(weight, 3)


# ---------------------------------------------------------------------------
# Outcome signal (plan 14.2).
# ---------------------------------------------------------------------------

# Strings that, when seen in tool output, indicate an error.
_ERROR_OUTPUT_HINTS = (
    "traceback (most recent call last)",
    "error: ",
    "errno",
    "command not found",
    "no such file or directory",
    "permission denied",
    "exit code: 1",
    "exit code: 2",
    "fatal:",
    "failed to",
    "exception:",
    "panic:",
)

# Tags / markers that indicate the turn was aborted by the user or system.
_INTERRUPT_MARKERS = (
    "<turn_aborted>",
    "<turn_interrupted>",
    "turn_aborted",
    "turn_interrupted",
    "[interrupted]",
    "user interrupted",
)


def _looks_like_error(text: str) -> bool:
    if not text:
        return False
    lowered = str(text).lower()
    # Short-circuit on strong hints; require the phrase to be reasonably
    # positioned (avoid matching it inside a normal file path story).
    return any(hint in lowered for hint in _ERROR_OUTPUT_HINTS)


def looks_interrupted(text: str) -> bool:
    if not text:
        return False
    lowered = str(text).lower()
    return any(marker in lowered for marker in _INTERRUPT_MARKERS)


def compute_outcome_signal(
    *,
    has_interrupt_marker: bool,
    recent_tool_errors: int,
    last_tool_success: bool,
    has_final_assistant_reply: bool,
    has_write_like_tools: bool,
    has_test_or_build: bool,
    is_exploration_only: bool,
) -> str:
    """Apply the ordered decision ladder from plan 14.2.

    Each branch returns immediately so the ordering is the contract.
    """
    if has_interrupt_marker:
        return "interrupted"
    if recent_tool_errors >= 3 and not last_tool_success:
        return "errored"
    if not has_final_assistant_reply:
        return "incomplete"
    if is_exploration_only:
        return "exploration"
    if has_write_like_tools or has_test_or_build:
        return "completed"
    if has_final_assistant_reply:
        return "partially_completed"
    return "unknown"


# ---------------------------------------------------------------------------
# Score formulas (plan 15).
# ---------------------------------------------------------------------------

def compute_value_score(
    *,
    weighted_local_files: float,
    weighted_remote_files: float,
    write_ops: int,
    edit_ops: int,
    successful_bash_count: int,
    command_intents: Dict[str, int],
    error_count: int,
    interrupted: bool,
) -> int:
    raw = (
        12.0 * weighted_local_files
        + 15.0 * weighted_remote_files
        + 8.0 * write_ops
        + 6.0 * edit_ops
        + 5.0 * successful_bash_count
        + 10.0 * command_intents.get("DEPLOY", 0)
        + 8.0 * command_intents.get("TEST", 0)
        + 6.0 * command_intents.get("GIT", 0)
        + 4.0 * command_intents.get("BUILD", 0)
        - 8.0 * error_count
        - 12.0 * (1 if interrupted else 0)
    )
    return int(round(clamp(raw, 0.0, 100.0)))


def compute_friction_score(
    *,
    error_count: int,
    failed_bash_count: int,
    repeated_command_count: int,
    interrupted: bool,
) -> int:
    raw = (
        10.0 * error_count
        + 8.0 * failed_bash_count
        + 6.0 * repeated_command_count
        + 12.0 * (1 if interrupted else 0)
    )
    return int(round(clamp(raw, 0.0, 100.0)))


def compute_action_density(*, tool_call_count: int, duration_ms: int) -> float:
    """Tool calls per minute (plan 15.4)."""
    minutes = max(duration_ms / 60000.0, 1.0)
    return round(tool_call_count / minutes, 2)


def weighted_file_count(file_mutation_stats: Dict[str, Dict], remote: bool) -> float:
    """Sum of ``net_value_weight`` over files in a bucket (plan 15.2)."""
    total = 0.0
    for stats in file_mutation_stats.values():
        if bool(stats.get("remote")) != remote:
            continue
        total += float(stats.get("net_value_weight", 1.0) or 0.0)
    return round(total, 3)


def count_repeated_commands(commands: List[str]) -> int:
    """Number of command strings that appear more than once (friction hint)."""
    seen: Dict[str, int] = {}
    for cmd in commands:
        key = _normalize_for_repeat(cmd)
        seen[key] = seen.get(key, 0) + 1
    return sum(count - 1 for count in seen.values() if count > 1)


def _normalize_for_repeat(cmd: str) -> str:
    # Strip env vars / leading whitespace; keep the core invocation.
    text = str(cmd or "").strip()
    if not text:
        return ""
    # collapse long strings so two big differing stdouts don't hide a repeat
    if len(text) > 200:
        text = text[:200]
    return text
