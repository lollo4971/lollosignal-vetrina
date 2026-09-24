"""Supporto per eseguire i test nella vetrina pubblica.

Aggiunge `src/` al percorso di import e marca come saltate le classi che
verificano l'aggancio a `bot.py`, che resta nel repository privato.
"""
import os
import sys
import unittest

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RADICE, "src"))

# Chi ha accesso al repository privato puo' puntare LSL_BOT_DIR alla sua
# cartella: allora anche i test di aggancio girano contro il bot vero.
BOT_DIR = os.getenv("LSL_BOT_DIR")
BOT_COMPLETO = bool(BOT_DIR) and os.path.exists(os.path.join(BOT_DIR, "bot.py"))
if BOT_COMPLETO:
    sys.path.append(BOT_DIR)

richiede_bot_completo = unittest.skipUnless(
    BOT_COMPLETO, "richiede il bot completo (repository privato)")

# storico.db (60.000 partite, 44 leghe) si rigenera dall'API e non sta nel
# repository: i test che leggono i numeri veri di lega si saltano senza.
STORICO = os.path.join(RADICE, "storico.db")
richiede_storico = unittest.skipUnless(
    (os.path.exists(STORICO) and os.path.getsize(STORICO) > 0) or BOT_COMPLETO,
    "richiede storico.db (archivio di 60.000 partite, non incluso)")
