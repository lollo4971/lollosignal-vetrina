"""Validate mathematical coherence of AI-generated pre-match predictions.

The AI can return predictions in two formats:

1. Legacy FT-only: {1x2, over25, gg, risultato_probabile}
2. Extended HT+FT: adds {ft_1x2, ft_over25, ft_gg, risultato_ft,
   ht_over05, ht_gg, risultato_ht}

Legacy and extended FT keys are aliases — if both present, their values
must coincide. HT keys are optional (backward compat): when absent, no
HT validation runs.
"""

import re

_SCORE_RE = re.compile(r"^\s*(\d+)\s*[-–:]\s*(\d+)\s*$")


def parse_score(score):
    """Return (home, away) ints from 'X-Y' string, or None if unparseable."""
    if not isinstance(score, str):
        return None
    m = _SCORE_RE.match(score)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


_VALID_1X2_FOR_SCORE = {
    "1":  lambda h, a: h > a,
    "X":  lambda h, a: h == a,
    "2":  lambda h, a: h < a,
    "1X": lambda h, a: h >= a,
    "X2": lambda h, a: h <= a,
    "12": lambda h, a: h != a,
}


def _norm(value):
    if value is None:
        return None
    s = str(value).strip().upper()
    return s if s else None


def _unify_alias(pred, old_key, new_key, errors):
    """Resolve a field that may appear under old_key, new_key, or both.

    If both set with different (normalized) values, append an alias-mismatch
    error and return the old_key value. Otherwise return whichever is set.
    """
    old_val = _norm(pred.get(old_key))
    new_val = _norm(pred.get(new_key))
    if old_val is not None and new_val is not None and old_val != new_val:
        errors.append(
            f"alias mismatch: '{old_key}'='{pred.get(old_key)}' "
            f"vs '{new_key}'='{pred.get(new_key)}'"
        )
    if old_val is not None:
        return old_val
    return new_val


def _normalize_yes_no(value, field_name, yes_aliases, no_aliases,
                      canonical_yes, canonical_no, errors):
    if value is None:
        errors.append(f"{field_name} mancante")
        return None
    if value in yes_aliases:
        return canonical_yes
    if value in no_aliases:
        return canonical_no
    errors.append(f"{field_name} '{value}' non riconosciuto")
    return None


_GG_YES = {"GG", "SI", "YES", "S"}
_GG_NO = {"NG", "NO", "N"}


def normalize_gg_label(value):
    """Riporta l'etichetta GG alla forma canonica 'GG'/'NG'.

    Da usare PRIMA di scrivere ft_gg su prematch_predictions: l'AI puo'
    restituire 'SI' al posto di 'GG' (successo tra il 16 e il 22/04/2026,
    9 righe). Un valore non riconosciuto non viene scartato ma restituito
    in maiuscolo, cosi' resta visibile in query invece di sparire.
    """
    if value is None:
        return None
    v = str(value).strip().upper()
    if not v:
        return None
    if v in _GG_YES:
        return "GG"
    if v in _GG_NO:
        return "NG"
    return v


def validate_prediction(pred):
    """Return list of coherence errors (empty = valid).

    Legacy keys: '1x2', 'over25', 'gg', 'risultato_probabile'.
    Extended FT aliases: 'ft_1x2', 'ft_over25', 'ft_gg', 'risultato_ft'.
    Optional HT keys: 'risultato_ht', 'ht_over05', 'ht_gg'.
    """
    errors = []

    one_x_two = _unify_alias(pred, "1x2", "ft_1x2", errors)
    over25 = _unify_alias(pred, "over25", "ft_over25", errors)
    gg = _unify_alias(pred, "gg", "ft_gg", errors)
    score_ft = _unify_alias(pred, "risultato_probabile", "risultato_ft", errors)

    parsed_ft = parse_score(score_ft) if score_ft else None
    if parsed_ft is None:
        errors.append(f"risultato FT non parsabile: '{score_ft}'")
        return errors
    home_ft, away_ft = parsed_ft
    total_ft = home_ft + away_ft

    if one_x_two is None:
        errors.append("1x2 mancante")
    else:
        check = _VALID_1X2_FOR_SCORE.get(one_x_two)
        if check is None:
            errors.append(f"1x2 '{one_x_two}' non riconosciuto")
        elif not check(home_ft, away_ft):
            expected = "1" if home_ft > away_ft else "2" if home_ft < away_ft else "X"
            errors.append(
                f"1x2='{one_x_two}' incoerente con {home_ft}-{away_ft} "
                f"(atteso '{expected}')"
            )

    over25_norm = _normalize_yes_no(
        over25, "over25",
        yes_aliases={"SI", "YES", "S"},
        no_aliases={"NO", "N"},
        canonical_yes="SI", canonical_no="NO",
        errors=errors,
    )
    if over25_norm == "SI" and total_ft <= 2:
        errors.append(
            f"over25='SI' incoerente con {home_ft}-{away_ft} "
            f"(totale {total_ft} < 2.5)"
        )
    if over25_norm == "NO" and total_ft >= 3:
        errors.append(
            f"over25='NO' incoerente con {home_ft}-{away_ft} "
            f"(totale {total_ft} > 2.5)"
        )

    gg_norm = _normalize_yes_no(
        gg, "gg",
        yes_aliases={"GG", "SI", "YES"},
        no_aliases={"NG", "NO"},
        canonical_yes="GG", canonical_no="NG",
        errors=errors,
    )
    both_scored_ft = home_ft >= 1 and away_ft >= 1
    if gg_norm == "GG" and not both_scored_ft:
        errors.append(
            f"gg='GG' incoerente con {home_ft}-{away_ft} "
            f"(una squadra non segna)"
        )
    if gg_norm == "NG" and both_scored_ft:
        errors.append(
            f"gg='NG' incoerente con {home_ft}-{away_ft} (entrambe segnano)"
        )

    score_ht_raw = pred.get("risultato_ht")
    ht_over05_raw = pred.get("ht_over05")
    ht_gg_raw = pred.get("ht_gg")
    has_any_ht = any(
        v is not None and str(v).strip()
        for v in (score_ht_raw, ht_over05_raw, ht_gg_raw)
    )
    if not has_any_ht:
        return errors

    parsed_ht = parse_score(score_ht_raw) if score_ht_raw else None
    if score_ht_raw and parsed_ht is None:
        errors.append(f"risultato_ht non parsabile: '{score_ht_raw}'")
        return errors
    if parsed_ht is None:
        return errors

    home_ht, away_ht = parsed_ht
    total_ht = home_ht + away_ht
    if home_ht > home_ft or away_ht > away_ft:
        errors.append(
            f"risultato_ht {home_ht}-{away_ht} > risultato_ft "
            f"{home_ft}-{away_ft} (HT non può superare FT)"
        )

    if ht_over05_raw is not None:
        ht_over05 = _normalize_yes_no(
            _norm(ht_over05_raw), "ht_over05",
            yes_aliases={"SI", "YES", "S"},
            no_aliases={"NO", "N"},
            canonical_yes="SI", canonical_no="NO",
            errors=errors,
        )
        if ht_over05 == "SI" and total_ht < 1:
            errors.append(
                f"ht_over05='SI' incoerente con HT {home_ht}-{away_ht} "
                f"(totale {total_ht} < 0.5)"
            )
        if ht_over05 == "NO" and total_ht >= 1:
            errors.append(
                f"ht_over05='NO' incoerente con HT {home_ht}-{away_ht} "
                f"(totale {total_ht} > 0.5)"
            )

    if ht_gg_raw is not None:
        ht_gg = _normalize_yes_no(
            _norm(ht_gg_raw), "ht_gg",
            yes_aliases={"GG", "SI", "YES"},
            no_aliases={"NG", "NO"},
            canonical_yes="GG", canonical_no="NG",
            errors=errors,
        )
        both_scored_ht = home_ht >= 1 and away_ht >= 1
        if ht_gg == "GG" and not both_scored_ht:
            errors.append(
                f"ht_gg='GG' incoerente con HT {home_ht}-{away_ht} "
                f"(una squadra non segna nel 1T)"
            )
        if ht_gg == "NG" and both_scored_ht:
            errors.append(
                f"ht_gg='NG' incoerente con HT {home_ht}-{away_ht} "
                f"(entrambe segnano nel 1T)"
            )

    return errors
