"""Test suite for the extended prediction_validator.

Covers legacy-only, extended-only, mixed-coherent, and several incoherent
cases (Norwich-Derby bug, HT>FT, alias mismatch, ht_over05/ht_gg incoherences).
"""

import sys
from prediction_validator import validate_prediction

VALID_CASES = [
    ("legacy FT-only", {
        "1x2": "1",
        "over25": "SI",
        "gg": "GG",
        "risultato_probabile": "2-1",
    }),
    ("extended HT+FT-only", {
        "ft_1x2": "1",
        "ft_over25": "SI",
        "ft_gg": "GG",
        "risultato_ft": "2-1",
        "risultato_ht": "1-0",
        "ht_over05": "SI",
        "ht_gg": "NG",
    }),
    ("mixed legacy+extended coherent", {
        "1x2": "1",
        "ft_1x2": "1",
        "over25": "SI",
        "ft_over25": "SI",
        "gg": "GG",
        "ft_gg": "GG",
        "risultato_probabile": "2-1",
        "risultato_ft": "2-1",
        "risultato_ht": "1-0",
        "ht_over05": "SI",
        "ht_gg": "NG",
    }),
]

INCOHERENT_CASES = [
    ("Norwich-Derby bug (1-2 but 1x2=1, NO, NG)", {
        "1x2": "1",
        "over25": "NO",
        "gg": "NG",
        "risultato_probabile": "1-2",
    }),
    ("HT > FT (2-1 HT, 1-1 FT)", {
        "1x2": "X",
        "over25": "NO",
        "gg": "NG",
        "risultato_probabile": "1-1",
        "risultato_ht": "2-1",
        "risultato_ft": "1-1",
    }),
    ("alias mismatch 1x2 vs ft_1x2", {
        "1x2": "1",
        "ft_1x2": "2",
        "over25": "SI",
        "gg": "GG",
        "risultato_probabile": "2-1",
        "risultato_ft": "2-1",
    }),
    ("ht_over05=SI ma HT 0-0", {
        "risultato_ht": "0-0",
        "ht_over05": "SI",
        "risultato_probabile": "1-0",
        "risultato_ft": "1-0",
        "1x2": "1",
        "over25": "NO",
        "gg": "NG",
    }),
    ("ht_gg=GG ma HT 2-0", {
        "risultato_ht": "2-0",
        "ht_gg": "GG",
        "risultato_probabile": "3-1",
        "risultato_ft": "3-1",
        "1x2": "1",
        "over25": "SI",
        "gg": "GG",
    }),
]


def run():
    all_ok = True

    print("=== CASI VALIDI (attesi: []) ===")
    for name, pred in VALID_CASES:
        errs = validate_prediction(pred)
        if errs == []:
            print(f"✅ {name}")
        else:
            print(f"❌ {name} — attesi 0 errori, ricevuti {len(errs)}: {errs}")
            all_ok = False

    print("\n=== CASI INCOERENTI (attesi: lista non vuota) ===")
    for name, pred in INCOHERENT_CASES:
        errs = validate_prediction(pred)
        if errs:
            print(f"✅ {name} — {len(errs)} errore/i rilevato/i: {errs}")
        else:
            print(f"❌ {name} — attesi errori ma ricevuti 0")
            all_ok = False

    print()
    if all_ok:
        print("🎉 Tutti i test passano")
        return 0
    print("💥 Uno o più test falliti")
    return 1


if __name__ == "__main__":
    sys.exit(run())
