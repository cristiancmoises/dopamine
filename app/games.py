"""Ten explicitly scripted, one-shot demonstrations. No chance-based payouts.

Selections only change the illustration; every valid round returns its stake and
adds exactly 100 fictional units. Results are generated here, never accepted from
a client, and stored with the idempotent round record. No real casino strategies.
"""
from dataclasses import dataclass

LEGACY_GAMES = ("prism", "orbit", "cards")
EXTRA_GAMES = ("dice", "blackjack", "baccarat", "bingo", "keno", "plinko", "treasure")
GAMES = LEGACY_GAMES + EXTRA_GAMES
BONUS = 100
STAKES = (100, 500, 1000)
SYMBOLS = {"diamond": "◇", "star": "☆", "infinity": "∞"}

@dataclass(frozen=True)
class Option:
    value: str
    label: str

# label is a translation key. Numbers need no translation.
OPTIONS = {
    "prism": (Option("diamond", "choice_diamond"), Option("star", "choice_star"), Option("infinity", "choice_infinity")),
    "orbit": tuple(Option(str(n), str(n)) for n in range(1, 7)),
    "cards": tuple(Option(str(n), str(n)) for n in range(1, 4)),
    "dice": tuple(Option(str(n), str(n)) for n in (6, 8, 10)),
    "blackjack": (Option("stand", "choice_stand"), Option("hit", "choice_hit")),
    "baccarat": (Option("player", "choice_player"), Option("banker", "choice_banker"), Option("tie", "choice_tie")),
    "bingo": tuple(Option(str(n), str(n)) for n in range(1, 4)),
    "plinko": tuple(Option(str(n), str(n)) for n in range(1, 6)),
    "treasure": tuple(Option(str(n), str(n)) for n in range(1, 4)),
}

def result_for(game: str, form: dict) -> dict:
    if game not in GAMES:
        raise ValueError("Unknown demonstration")
    if game == "keno":
        picks = [form.get("n1", "1"), form.get("n2", "2"), form.get("n3", "3")]
        if any(p not in {str(n) for n in range(1, 13)} for p in picks) or len(set(picks)) != 3:
            raise ValueError("Choose three different numbers from 1 to 12")
        numbers = sorted(int(n) for n in picks)
        return {"version": 1, "game": game, "kind": "numbers", "values": numbers,
                "choice_label": "keno_choice", "scripted": True}
    choices = OPTIONS[game]
    # Keep v1 card form submissions compatible. 'card' remains the old input name.
    selection = form.get("choice", form.get("card", choices[0].value) if game == "cards" else choices[0].value)
    valid = {option.value: option.label for option in choices}
    if selection not in valid:
        raise ValueError("Invalid demonstration selection")
    result = {"version": 1, "game": game, "choice": selection,
              "choice_label": valid[selection], "scripted": True}
    if game == "prism":
        result.update(kind="symbols", values=[SYMBOLS[selection]] * 3)
    elif game == "orbit":
        result.update(kind="wheel", values=[int(selection)])
    elif game == "cards":
        result.update(kind="cards", values=["A♠", "A♥", "A♦"], selected=int(selection))
    elif game == "dice":
        die = int(selection) // 2
        result.update(kind="dice", values=[die, die], total=die * 2)
    elif game == "blackjack":
        result.update(kind="blackjack", values=["A♠", "K♥"] if selection == "stand" else ["7♣", "5♦", "9♥"], total=21)
    elif game == "baccarat":
        result.update(kind="baccarat", player=9 if selection != "banker" else 7,
                      banker=9 if selection != "player" else 7, values=[])
    elif game == "bingo":
        offset = (int(selection) - 1) * 9
        result.update(kind="bingo", values=list(range(offset + 1, offset + 10)), hits=list(range(offset + 1, offset + 4)))
    elif game == "plinko":
        entry = int(selection)
        # A deterministic visual route, not a physics engine or a probability model.
        trail = [entry, min(5, entry + 1), max(1, entry - 1), entry]
        result.update(kind="plinko", values=trail, selected=entry)
    elif game == "treasure":
        result.update(kind="treasure", values=["◇", "◇", "◇"], selected=int(selection))
    return result
