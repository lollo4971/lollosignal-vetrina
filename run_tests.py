"""Esegue tutti i test della vetrina: python3 run_tests.py"""
import os
import sys
import unittest

QUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(QUI, "src"))
sys.path.insert(0, os.path.join(QUI, "tests"))
os.chdir(os.path.join(QUI, "tests"))

suite = unittest.defaultTestLoader.discover(".", pattern="test_*.py")
esito = unittest.TextTestRunner(verbosity=1).run(suite)
sys.exit(0 if esito.wasSuccessful() else 1)
