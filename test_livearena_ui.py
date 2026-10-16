import os
import sys
import cv2

MY_CHAMPIONS = [
    "arena_live_fabian",
    "arena_live_harima",
    "arena_live_mikage",
    "arena_live_fenax",
    "arena_live_ankora",
    "arena_live_ronda",
    "arena_live_mithrala",
    "arena_live_udk",
]

BAN_CHAMPIONS = ["arena_live_ban_predator", "arena_live_ban_solonar"]
LEAD_CHAMPIONS = [
    "arena_live_lead_fabian",
    "arena_live_lead_ankora",
    "arena_live_lead_harima",
    "arena_live_lead_mikage",
]


def match(screen, name, threshold=0.78, grayscale=False):
    path = os.path.join("bilder", name + ".PNG")
    if not os.path.exists(path):
        print(f"  {name}: BRAK PLIKU -> {path}")
        return False, 0.0

    templ = cv2.imread(path, cv2.IMREAD_COLOR)
    if templ is None:
        print(f"  {name}: NIE MOGĘ ODCZYTAĆ")
        return False, 0.0

    if grayscale:
        a = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        b = cv2.cvtColor(templ, cv2.COLOR_BGR2GRAY)
    else:
        a, b = screen, templ

    if b.shape[0] > a.shape[0] or b.shape[1] > a.shape[1]:
        print(f"  {name}: WZORZEC WIĘKSZY OD SCREENA")
        return False, 0.0

    res = cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED)
    _, score, _, _ = cv2.minMaxLoc(res)
    found = score >= threshold
    print(f"  {name}: {'TAK' if found else 'NIE'} (score={score:.3f}, próg={threshold:.2f})")
    return found, score


def test_one(path):
    print("\n" + "=" * 70)
    print("OFFLINE LIVE ARENA TEST — ZERO KLIKNIĘĆ")
    print("Screen:", path)
    print("=" * 70)

    if not os.path.exists(path):
        print("BŁĄD: plik screena nie istnieje.")
        return

    screen = cv2.imread(path, cv2.IMREAD_COLOR)
    if screen is None:
        print("BŁĄD: nie udało się odczytać obrazu.")
        return

    print("\n[FAZA]")
    your_turn, _ = match(screen, "arena_live_your_turn", 0.78, False)
    pick, _ = match(screen, "arena_live_pick_your_champions", 0.78, True)
    ban, _ = match(screen, "live_arena_ban_champions", 0.82, False)
    leader, _ = match(screen, "live_arena_pick_leader", 0.82, False)

    print("\n[DECYZJA]")
    if not your_turn:
        print("Brak YOUR TURN -> bot nie powinien nic kliknąć.")
        return

    if ban:
        print("YOUR TURN + BAN CHAMPIONS")
        for name in BAN_CHAMPIONS:
            found, _ = match(screen, name, 0.76, False)
            if found:
                print(f"DECYZJA: ban priorytetowy -> {name}")
                return
        print("DECYZJA: brak priorytetu -> ban SLOT 1 przeciwnika")
        return

    if leader:
        print("YOUR TURN + PICK LEADER")
        for name in LEAD_CHAMPIONS:
            found, _ = match(screen, name, 0.76, False)
            if found:
                print(f"DECYZJA: lider -> {name}")
                return
        print("DECYZJA: brak Fabian/Ankora/Harima/Mikage -> losowy slot awaryjny")
        return

    if pick:
        print("YOUR TURN + PICK CHAMPIONS")
        filt, _ = match(screen, "arena_live_filter", 0.76, False)
        if not filt:
            print("DECYZJA: brak filtra mieczy -> bot powinien czekać")
            return
        print("DECYZJA: klik Live Arena tag, potem szukanie championa")
        for name in MY_CHAMPIONS:
            found, _ = match(screen, name, 0.82, True)
            if found:
                print(f"Pierwszy dostępny champion -> {name}")
                return
        print("Nie wykryto żadnego championa z priorytetu.")
        return

    print("YOUR TURN jest widoczne, ale nie rozpoznano Pick/Ban/Leader.")


def main():
    if len(sys.argv) < 2:
        print('Użycie: py test_livearena_ui.py "pick.png" "ban.png" "leader.png"')
        return
    for p in sys.argv[1:]:
        test_one(p)


if __name__ == "__main__":
    main()
