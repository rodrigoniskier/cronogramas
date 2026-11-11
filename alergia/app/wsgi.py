import os
import sys

# Adiciona a pasta do app ao caminho, para o PythonAnywhere encontrar os módulos
path = os.path.dirname(os.path.abspath(__file__))
if path not in sys.path:
    sys.path.insert(0, path)

from app import app as application  # noqa: E402
