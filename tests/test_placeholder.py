"""Placeholder de la suite de tests.

Los tests reales llegan en la FASE 3 (`ledger.py`) y la FASE 5 (`mail.py`).
Este fichero sólo verifica que el andamiaje importa correctamente.
"""

import config
import graph
import ledger
import mail
import main


def test_modules_importables() -> None:
    for module in (config, graph, ledger, mail, main):
        assert module.__doc__
