"""Key figures shown on screen (panel cards and broadcast graphic), computed from the data, never by the model.

The agents used to pick these figures as free text, which produced cards such as "63% Possession" (whose?) or
"24 Shots" (one team only). Here every card names the teams and shows both sides when a figure is a comparison.
Only fixed labels are translated; the numbers are the same in every language.
"""
from . import analytics as an
from .schema import Match

LABELS = {
    "en": {"possession": "Possession", "shots": "Shots", "xg": "xG", "win_prob": "Win probability",
           "shot_speed": "Shot speed", "possession_prev": "Possession (prev. 10')", "shots_prev": "Shots (prev. 10')",
           "red_cards": "Red cards", "territory": "Territory", "press_height": "Press height",
           "possession_changes": "Possession changes/min", "passes_per_sequence": "Passes per move",
           "turnovers": "Turnovers/min", "goals": "Goals", "chances_created": "Chances created",
           "progressive_passes": "Progressive passes", "saves": "Saves", "impact": "Impact", "ball_wins": "Ball wins"},
    "pt": {"possession": "Posse", "shots": "Remates", "xg": "xG", "win_prob": "Prob. de vitória",
           "shot_speed": "Velocidade do remate", "possession_prev": "Posse (10' antes)",
           "shots_prev": "Remates (10' antes)", "red_cards": "Cartões vermelhos", "territory": "Território",
           "press_height": "Altura da pressão", "possession_changes": "Trocas de posse/min",
           "passes_per_sequence": "Passes por jogada", "turnovers": "Perdas de bola/min", "goals": "Golos",
           "chances_created": "Chances criadas", "progressive_passes": "Passes progressivos", "saves": "Defesas", "impact": "Impacto", "ball_wins": "Bolas recuperadas"},
    "es": {"possession": "Posesión", "shots": "Tiros", "xg": "xG", "win_prob": "Prob. de victoria",
           "shot_speed": "Velocidad del tiro", "possession_prev": "Posesión (10' antes)",
           "shots_prev": "Tiros (10' antes)", "red_cards": "Tarjetas rojas", "territory": "Territorio",
           "press_height": "Altura de la presión", "possession_changes": "Cambios de posesión/min",
           "passes_per_sequence": "Pases por jugada", "turnovers": "Pérdidas/min", "goals": "Goles",
           "chances_created": "Ocasiones creadas", "progressive_passes": "Pases progresivos", "saves": "Paradas", "impact": "Impacto", "ball_wins": "Balones recuperados"},
    "fr": {"possession": "Possession", "shots": "Tirs", "xg": "xG", "win_prob": "Prob. de victoire",
           "shot_speed": "Vitesse du tir", "possession_prev": "Possession (10' avant)",
           "shots_prev": "Tirs (10' avant)", "red_cards": "Cartons rouges", "territory": "Territoire",
           "press_height": "Hauteur du pressing", "possession_changes": "Changements de possession/min",
           "passes_per_sequence": "Passes par action", "turnovers": "Pertes de balle/min", "goals": "Buts",
           "chances_created": "Occasions créées", "progressive_passes": "Passes progressives", "saves": "Arrêts", "impact": "Impact", "ball_wins": "Ballons récupérés"},
    "de": {"possession": "Ballbesitz", "shots": "Schüsse", "xg": "xG", "win_prob": "Siegchance",
           "shot_speed": "Schussgeschwindigkeit", "possession_prev": "Ballbesitz (10' zuvor)",
           "shots_prev": "Schüsse (10' zuvor)", "red_cards": "Rote Karten", "territory": "Raumkontrolle",
           "press_height": "Pressinghöhe", "possession_changes": "Ballwechsel/Min",
           "passes_per_sequence": "Pässe pro Angriff", "turnovers": "Ballverluste/Min", "goals": "Tore",
           "chances_created": "Chancen kreiert", "progressive_passes": "Progressive Pässe", "saves": "Paraden", "impact": "Wirkung", "ball_wins": "Balleroberungen"},
    "it": {"possession": "Possesso", "shots": "Tiri", "xg": "xG", "win_prob": "Prob. di vittoria",
           "shot_speed": "Velocità del tiro", "possession_prev": "Possesso (10' prima)",
           "shots_prev": "Tiri (10' prima)", "red_cards": "Cartellini rossi", "territory": "Territorio",
           "press_height": "Altezza del pressing", "possession_changes": "Cambi di possesso/min",
           "passes_per_sequence": "Passaggi per azione", "turnovers": "Palle perse/min", "goals": "Gol",
           "chances_created": "Occasioni create", "progressive_passes": "Passaggi progressivi", "saves": "Parate", "impact": "Impatto", "ball_wins": "Palle recuperate"},
}


def pct(x: float) -> str:
    return f"{round(x)}%"


def frac(x: float) -> str:
    return f"{round(x * 100)}%"


def arrow(a: str, b: str) -> str:
    return f"{a} → {b}"


def chip(label: str, value: str, detail: str = "") -> dict:
    return {"label": label, "value": value, "detail": detail}


def _recap(match: Match, L: dict) -> list[dict]:
    s = an.match_summary(match)
    h, a = match.home.short, match.away.short
    both = f"{h} – {a}"
    return [
        chip(L["possession"], f"{pct(s['possession_pct']['home'])} – {pct(s['possession_pct']['away'])}", both),
        chip(L["shots"], f"{s['shots']['home']} – {s['shots']['away']}", both),
        chip(L["xg"], f"{s['xg']['home']:.2f} – {s['xg']['away']:.2f}", both),
    ]


def _shot_chips(match: Match, f: dict, L: dict, third: str) -> list[dict]:
    """Shared by goals and big chances: shot quality, shot speed (or possession when the feed has none)."""
    side, short = f["side"], match.team(f["side"]).short
    recent = f["last_10_min_before_moment"]
    chips = [chip(L["xg"], f"{f['xg']:.2f}" if f.get("xg") is not None else "–", f.get("player") or short)]
    if f.get("shot_speed_kmh"):
        chips.append(chip(L["shot_speed"], f"{f['shot_speed_kmh']:.0f} km/h", short))
    else:
        chips.append(chip(L["possession_prev"], pct(recent["possession_pct"][side]), short))
    if third == "win_prob" and f.get("win_probability_before") and f.get("win_probability_after"):
        b, a = f["win_probability_before"][side], f["win_probability_after"][side]
        chips.append(chip(L["win_prob"], arrow(frac(b), frac(a)), short))
    else:
        chips.append(chip(L["shots_prev"], str(recent["shots"][side]), short))
    return chips


def _red_card(match: Match, f: dict, L: dict) -> list[dict]:
    h, a = match.home.short, match.away.short
    chips = []
    if f.get("win_probability_before") and f.get("win_probability_after"):
        for side, short in (("home", h), ("away", a)):
            chips.append(chip(L["win_prob"], arrow(frac(f["win_probability_before"][side]),
                                                   frac(f["win_probability_after"][side])), short))
    chips.append(chip(L["red_cards"], str(f["red_cards_so_far"][f["side"]]), match.team(f["side"]).short))
    return chips


def _shift(match: Match, f: dict, L: dict) -> list[dict]:
    side, short = f["side"], match.team(f["side"]).short
    b, a = f["window_before_10_min"], f["window_after_10_min"]
    chips = [chip(L["territory"], arrow(pct(b["field_tilt_pct"][side]), pct(a["field_tilt_pct"][side])), short)]
    pb, pa = b["press_height_m"][side], a["press_height_m"][side]
    if pb is not None and pa is not None:
        chips.append(chip(L["press_height"], f"{pb:.0f} → {pa:.0f} m", short))
    chips.append(chip(L["possession"], arrow(pct(b["possession_pct"][side]), pct(a["possession_pct"][side])), short))
    return chips


def _chaos(match: Match, f: dict, L: dict) -> list[dict]:
    both = f"{match.home.short} + {match.away.short}"
    b, d = f["ten_minutes_before_spell"], f["during_spell"]
    return [
        chip(L["possession_changes"], arrow(f"{b['sequences_per_min']:.1f}", f"{d['sequences_per_min']:.1f}"), both),
        chip(L["passes_per_sequence"], arrow(f"{b['avg_passes_per_sequence']:.1f}",
                                             f"{d['avg_passes_per_sequence']:.1f}"), both),
        chip(L["turnovers"], arrow(f"{b['turnovers_per_min']:.1f}", f"{d['turnovers_per_min']:.1f}"), both),
    ]


def _is_keeper(p: dict) -> bool:
    """The position when the feed has one; otherwise a player whose only actions are saves."""
    return p["position"] == "GK" or (p["saves"] > 0 and not (p["shots"] or p["chances_created"]
                                                             or p["progressive_passes"]))


def _player(f: dict, L: dict) -> list[dict]:
    """Cards depend on the role: a keeper is described by saves, an outfielder by what he actually did."""
    p, share = f["player"], f["share_of_team_pct"]
    team = f.get("team_short", p["team"][:3].upper())
    rank = f"#{p['rank_in_team']} {team}"
    if _is_keeper(p):
        return [chip(L["saves"], str(p["saves"]), team), chip(L["impact"], f"{p['impact']:.1f}", rank)]
    cards = [
        chip(L["chances_created"], str(p["chances_created"]), f"{team} {share['chances_created']}%"),
        chip(L["progressive_passes"], str(p["progressive_passes"]), f"{team} {share['progressive_passes']}%"),
    ]
    # third card: goals if he scored, otherwise ball wins if he made a few, otherwise his impact score
    if p["goals"] > 0:
        cards.append(chip(L["goals"], str(p["goals"]), f"{L['xg']} {p['xg']:.2f}"))
    elif p["ball_wins"] >= 3:
        cards.append(chip(L["ball_wins"], str(p["ball_wins"]), f"{team} {share['ball_wins']}%"))
    else:
        cards.append(chip(L["impact"], f"{p['impact']:.1f}", rank))
    return cards


def build_chips(match: Match, moment: dict | None, player: dict | None, language: str) -> list[dict]:
    """Three key figures for the current selection, with team names and both sides of a comparison."""
    L = LABELS.get(language, LABELS["en"])
    try:
        if player is not None:
            player = {**player, "team_short": match.team(player["player"]["side"]).short}
            return _player(player, L)
        if moment is None:
            return _recap(match, L)
        f, kind = moment["facts"], moment["type"]
        if kind == "goal":
            return _shot_chips(match, f, L, "win_prob")
        if kind == "big_chance":
            return _shot_chips(match, f, L, "shots_prev")
        if kind == "red_card":
            return _red_card(match, f, L)
        if kind == "tactical_shift":
            return _shift(match, f, L)
        if kind == "chaotic_spell":
            return _chaos(match, f, L)
    except (KeyError, TypeError):  # facts from an unusual feed: show nothing rather than a wrong figure
        return []
    return []
