"""Start the full RAID bot with a selected Live Arena draft profile.

Usage:
    py profile_start.py symbiont

This intentionally executes raid.py from the beginning, so the original startup
sequence (including closeadds / unfinishedBattleCheck and any other currently
enabled raid.py tasks) is preserved.  The selected profile is forwarded to
arenalive through sys.argv and an environment variable.
"""
from __future__ import annotations

import os
from pathlib import Path
import runpy
import sys


BOT_DIR = Path(__file__).resolve().parent
PROFILES_DIR = BOT_DIR / "draft_profiles"


def _enable_ansi():
    # Modern PowerShell/Windows Terminal normally supports ANSI already.
    # os.system("") enables processing in many classic Windows console setups.
    try:
        os.system("")
    except Exception:
        pass


def _print_hello_if_raid_does_not():
    """Keep HELLO WORLD exactly once for profile launches."""
    raid_path = BOT_DIR / "raid.py"
    try:
        source = raid_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        source = ""

    # Older/current user raid.py versions may already print this greeting.
    if "HELLO WORLD!" in source:
        return

    _enable_ansi()
    print("\033[1;3;95mHELLO WORLD!\033[0m")


def _profile_name(raw: str) -> str:
    name = Path(str(raw).strip()).stem.lower()
    if not name or not all(ch.isalnum() or ch in "_-" for ch in name):
        raise SystemExit(f"Nieprawidłowa nazwa profilu: {raw!r}")
    return name


def main():
    if len(sys.argv) < 2:
        raise SystemExit(
            "Podaj nazwę profilu, np.: py profile_start.py symbiont"
        )

    profile = _profile_name(sys.argv[1])
    profile_file = PROFILES_DIR / f"{profile}.json"

    if not profile_file.exists():
        available = ", ".join(
            sorted(p.stem for p in PROFILES_DIR.glob("*.json"))
        ) or "(brak)"
        raise SystemExit(
            f"Nie znaleziono profilu '{profile}'. Dostępne: {available}"
        )

    raid_path = BOT_DIR / "raid.py"
    if not raid_path.exists():
        raise SystemExit(
            "Brak raid.py w folderze bota. Profilowa komenda uruchamia teraz "
            "pełny bot od początku, więc raid.py musi znajdować się obok "
            "profile_start.py."
        )

    # Redundant forwarding by argv + environment makes this robust both for
    # current and future profile loaders.
    os.environ["LIVEARENA_DRAFT_PROFILE"] = profile

    extra = sys.argv[2:]
    sys.argv = [str(raid_path), "--draft-profile", profile, *extra]

    os.chdir(BOT_DIR)
    _print_hello_if_raid_does_not()

    # Execute the user's existing raid.py unchanged from its first line.
    runpy.run_path(str(raid_path), run_name="__main__")


if __name__ == "__main__":
    main()
