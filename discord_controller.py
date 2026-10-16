import os
import subprocess
import sys
import time
import asyncio
import ctypes
from ctypes import wintypes
from pathlib import Path

import discord
from discord.ext import commands
import pyautogui


# ============================================================
# KONFIGURACJA
# ============================================================

PROJECT_DIR = Path(__file__).resolve().parent
RAID_SCRIPT = PROJECT_DIR / "raid.py"
PID_FILE = PROJECT_DIR / "discord_raid.pid"

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
ALLOWED_USER_ID = int(os.getenv("DISCORD_ALLOWED_USER_ID", "0") or 0)
ALLOWED_CHANNEL_ID = int(os.getenv("DISCORD_ALLOWED_CHANNEL_ID", "0") or 0)

RAID_LAUNCH_PATH = os.getenv(
    "RAID_LAUNCH_PATH",
    r"C:\Users\procu\OneDrive\Pulpit\rsl.lnk.lnk",
).strip()

# Ile maksymalnie czekamy na samo okno gry.
RAID_WINDOW_TIMEOUT = 120

# Ile maksymalnie czekamy aż gra faktycznie załaduje Bastion/UI.
RAID_UI_TIMEOUT = 180

# Wzorce oznaczające, że główny interfejs RAID jest już gotowy.
# Najważniejszy jest battle.PNG, bo raid.py potem właśnie ten przycisk klika.
RAID_READY_TEMPLATES = [
    PROJECT_DIR / "bilder" / "battle.PNG",
    PROJECT_DIR / "bilder" / "bastion.PNG",
]


# ============================================================
# PID raid.py
# ============================================================

def read_pid():
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def write_pid(pid):
    PID_FILE.write_text(str(pid), encoding="utf-8")


def clear_pid():
    try:
        PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def pid_is_running(pid):
    if not pid:
        return False

    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return str(pid) in result.stdout
    except Exception:
        return False


def current_bot_pid():
    pid = read_pid()

    if pid and pid_is_running(pid):
        return pid

    clear_pid()
    return None


# ============================================================
# OKNO RAID
# ============================================================

def _find_raid_hwnd():
    user32 = ctypes.windll.user32
    result = {"hwnd": None}

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True

        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True

        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip().lower()

        if title in {
            "raid: shadow legends",
            "raid shadow legends",
        }:
            result["hwnd"] = hwnd
            return False

        return True

    user32.EnumWindows(enum_proc, 0)
    return result["hwnd"]


def raid_window_is_open():
    return _find_raid_hwnd() is not None


def focus_raid_window():
    """Przywraca i próbuje ustawić RAID na pierwszym planie."""
    hwnd = _find_raid_hwnd()
    if not hwnd:
        return False

    try:
        user32 = ctypes.windll.user32
        SW_RESTORE = 9
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


# ============================================================
# GOTOWOŚĆ UI RAID
# ============================================================

def _locate_ready_template():
    """
    Zwraca nazwę wykrytego wzorca UI albo None.
    Dzięki temu nie uruchamiamy raid.py zaraz po pojawieniu się samego okna gry.
    """
    for template in RAID_READY_TEMPLATES:
        if not template.exists():
            continue

        try:
            found = pyautogui.locateOnScreen(
                str(template),
                grayscale=True,
                confidence=0.80,
                minSearchTime=0.15,
            )
            if found:
                return template.name
        except Exception:
            pass

    return None


def wait_for_raid_window(timeout=RAID_WINDOW_TIMEOUT):
    started = time.monotonic()

    while time.monotonic() - started < timeout:
        if raid_window_is_open():
            return True
        time.sleep(1)

    return False


def wait_for_raid_ui(timeout=RAID_UI_TIMEOUT):
    """
    Czeka aż na ekranie pojawi się właściwy UI Bastionu.
    Jeśli nie ma żadnego z plików kontrolnych w bilder, używa bezpiecznego
    fallbacku: 30 sekund od pojawienia się okna.
    """
    available = [p for p in RAID_READY_TEMPLATES if p.exists()]

    if not available:
        # Nie zgadujemy po samym tytule okna; dajemy grze czas na pełne ładowanie.
        time.sleep(30)
        return raid_window_is_open(), "fallback 30s (brak battle.PNG/bastion.PNG)"

    started = time.monotonic()

    while time.monotonic() - started < timeout:
        if not raid_window_is_open():
            time.sleep(1)
            continue

        ready = _locate_ready_template()
        if ready:
            return True, ready

        time.sleep(1)

    return False, None


# ============================================================
# URUCHAMIANIE RAID
# ============================================================

def find_raid_launcher():
    launcher = Path(RAID_LAUNCH_PATH)

    if launcher.exists():
        return launcher

    return None


def launch_raid_game():
    launcher = find_raid_launcher()

    if launcher is None:
        return False, f"Nie znaleziono skrótu RAID: {RAID_LAUNCH_PATH}"

    try:
        os.startfile(str(launcher))
        return True, f"Uruchamiam RAID przez: {launcher}"
    except Exception as exc:
        return False, f"Nie udało się uruchomić RAID: {exc}"


# ============================================================
# raid.py
# ============================================================

def _powershell_literal(value):
    """Bezpieczne umieszczenie ścieżki w pojedynczym cudzysłowie PowerShell."""
    return "'" + str(value).replace("'", "''") + "'"


def _console_python_exe():
    """
    Controller może działać przez pythonw.exe, ale raid.py ma być uruchomiony
    przez python.exe, żeby wszystkie printy były widoczne w konsoli.
    """
    current = Path(sys.executable)

    if current.name.lower() == "pythonw.exe":
        console_python = current.with_name("python.exe")
        if console_python.exists():
            return console_python

    return current


def start_raid_script():
    if not RAID_SCRIPT.exists():
        return False, f"Nie znaleziono: {RAID_SCRIPT}"

    running_pid = current_bot_pid()
    if running_pid:
        return False, f"raid.py już działa. PID konsoli: {running_pid}"

    python_exe = _console_python_exe()

    # raid.py uruchamiamy w osobnym, WIDOCZNYM PowerShellu.
    # -NoExit pozostawia okno otwarte również po ewentualnym błędzie,
    # dzięki czemu traceback/logi nie znikną.
    ps_command = (
        "$Host.UI.RawUI.WindowTitle = 'RAID BOT - LOGI'; "
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        f"Set-Location -LiteralPath {_powershell_literal(PROJECT_DIR)}; "
        f"& {_powershell_literal(python_exe)} {_powershell_literal(RAID_SCRIPT)}"
    )

    process = subprocess.Popen(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoExit",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            ps_command,
        ],
        cwd=str(PROJECT_DIR),
        creationflags=(
            subprocess.CREATE_NEW_CONSOLE
            | subprocess.CREATE_NEW_PROCESS_GROUP
        ),
    )

    # Zapisujemy PID PowerShella. !raid stop używa taskkill /T,
    # więc zamknie zarówno PowerShell, jak i uruchomiony w nim raid.py.
    write_pid(process.pid)

    return (
        True,
        f"Uruchomiono raid.py w widocznym PowerShellu. PID konsoli: {process.pid}",
    )


def stop_raid_script():
    pid = current_bot_pid()

    if not pid:
        return False, "raid.py nie jest uruchomiony."

    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        clear_pid()
        return True, f"Zatrzymano raid.py. PID: {pid}"
    except Exception as exc:
        return False, f"Nie udało się zatrzymać raid.py: {exc}"


# ============================================================
# PEŁNY START
# ============================================================

async def ensure_raid_ready(ctx):
    """
    Zapewnia:
      1. gra uruchomiona,
      2. okno istnieje,
      3. Bastion/UI faktycznie załadowany,
      4. RAID jest na pierwszym planie.
    """

    if not raid_window_is_open():
        await ctx.send("🎮 RAID jest zamknięty. Uruchamiam grę...")

        ok, message = await asyncio.to_thread(launch_raid_game)
        await ctx.send(("✅ " if ok else "❌ ") + message)

        if not ok:
            return False

        await ctx.send(
            f"⏳ Czekam na okno RAID (maks. {RAID_WINDOW_TIMEOUT}s)..."
        )

        window_ok = await asyncio.to_thread(
            wait_for_raid_window,
            RAID_WINDOW_TIMEOUT,
        )

        if not window_ok:
            await ctx.send("❌ Okno Raid: Shadow Legends nie pojawiło się.")
            return False

    else:
        await ctx.send("🎮 Okno RAID jest już uruchomione.")

    # Samo istnienie okna to za mało. To naprawia sytuację ze screena:
    # raid.py uruchamiał się podczas ekranu ładowania i widział
    # 'arena live is not active'.
    await ctx.send(
        f"⏳ Czekam aż załaduje się właściwy interfejs RAID "
        f"(maks. {RAID_UI_TIMEOUT}s)..."
    )

    ready, detected_by = await asyncio.to_thread(
        wait_for_raid_ui,
        RAID_UI_TIMEOUT,
    )

    if not ready:
        await ctx.send(
            "❌ Okno gry działa, ale nie wykryłem gotowego interfejsu. "
            "Nie uruchamiam raid.py."
        )
        return False

    await asyncio.to_thread(focus_raid_window)
    await asyncio.sleep(1.0)

    await ctx.send(f"✅ RAID gotowy. Wykryto UI: `{detected_by}`")
    return True


# ============================================================
# DISCORD
# ============================================================

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None,
)


async def authorized(ctx):
    if ctx.author.id != ALLOWED_USER_ID:
        return False

    if ALLOWED_CHANNEL_ID and ctx.channel.id != ALLOWED_CHANNEL_ID:
        return False

    return True


@bot.event
async def on_ready():
    print(f"Discord controller aktywny jako: {bot.user}")
    print(f"Projekt: {PROJECT_DIR}")
    print("Komendy:")
    print("  !raid start")
    print("  !raid stop")
    print("  !raid status")
    print("  !raid restart")


@bot.group(name="raid", invoke_without_command=True)
async def raid(ctx):
    if not await authorized(ctx):
        return

    await ctx.send(
        "Komendy: `!raid start`, `!raid stop`, `!raid status`, `!raid restart`"
    )


@raid.command(name="start")
async def raid_start(ctx):
    if not await authorized(ctx):
        return

    running_pid = current_bot_pid()

    if running_pid:
        await ctx.send(f"ℹ️ raid.py już działa. PID: `{running_pid}`")
        return

    if not await ensure_raid_ready(ctx):
        return

    ok, message = await asyncio.to_thread(start_raid_script)
    await ctx.send(("✅ " if ok else "ℹ️ ") + message)


@raid.command(name="stop")
async def raid_stop(ctx):
    if not await authorized(ctx):
        return

    ok, message = await asyncio.to_thread(stop_raid_script)
    await ctx.send(("✅ " if ok else "ℹ️ ") + message)


@raid.command(name="status")
async def raid_status(ctx):
    if not await authorized(ctx):
        return

    game_open = await asyncio.to_thread(raid_window_is_open)
    pid = await asyncio.to_thread(current_bot_pid)

    if game_open:
        detected_by = await asyncio.to_thread(_locate_ready_template)
        if detected_by:
            game_status = f"🟢 RAID otwarty i gotowy (`{detected_by}`)"
        else:
            game_status = "🟡 RAID otwarty, ale UI jeszcze niegotowe"
    else:
        game_status = "🔴 RAID zamknięty"

    if pid:
        bot_status = f"🟢 raid.py działa (PID `{pid}`)"
    else:
        bot_status = "🔴 raid.py nie działa"

    await ctx.send(f"{game_status}\n{bot_status}")


@raid.command(name="restart")
async def raid_restart(ctx):
    if not await authorized(ctx):
        return

    pid = current_bot_pid()

    if pid:
        await asyncio.to_thread(stop_raid_script)
        await ctx.send("🔄 Zatrzymano poprzednią instancję raid.py.")

    if not await ensure_raid_ready(ctx):
        return

    ok, message = await asyncio.to_thread(start_raid_script)
    await ctx.send(("✅ " if ok else "ℹ️ ") + message)


if __name__ == "__main__":
    if not BOT_TOKEN:
        raise SystemExit(
            "Brak DISCORD_BOT_TOKEN. "
            "Ustaw token w zmiennej środowiskowej Windows."
        )

    if not ALLOWED_USER_ID:
        raise SystemExit(
            "Brak DISCORD_ALLOWED_USER_ID. "
            "Ustaw swój Discord User ID."
        )

    bot.run(BOT_TOKEN)
