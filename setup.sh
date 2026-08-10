#!/usr/bin/env bash
# Instalación en un solo comando:
#
#   bash setup.sh
#
# Crea el entorno virtual, instala las dependencias y prepara el .env.
# Es idempotente: se puede ejecutar las veces que haga falta.

set -euo pipefail

cd "$(dirname "$0")"

echo "==> Comprobando Python 3..."
if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: no hay python3 instalado."
    echo "En macOS, ejecuta 'xcode-select --install' y vuelve a intentarlo."
    exit 1
fi
python3 --version

echo "==> Creando el entorno virtual (.venv)..."
if [ ! -d .venv ]; then
    python3 -m venv .venv
fi

echo "==> Instalando dependencias..."
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet msal httpx python-dotenv

if [ ! -f .env ]; then
    echo "==> Creando .env a partir de .env.example..."
    cp .env.example .env
    echo
    echo "  Falta rellenar el .env con tus datos. Ábrelo con:"
    echo "      open -e .env      (macOS)"
    echo "      nano .env         (Linux)"
    echo
    echo "  Rellena al menos estas tres líneas:"
    echo "      IMAP_HOST=imap.gmail.com"
    echo "      IMAP_USER=tucorreo@gmail.com"
    echo "      IMAP_PASSWORD=<contraseña de aplicación, 16 letras sin espacios>"
else
    echo "==> El .env ya existe, no se toca."
fi

echo
echo "==> Listo."
echo
echo "Para volcar los correos de Meta (sólo lectura, no marca nada como leído):"
echo "    ./.venv/bin/python src/mail.py --all --limit 20"
echo
echo "Para probar la conexión con OneDrive:"
echo "    ./.venv/bin/python src/graph.py"
