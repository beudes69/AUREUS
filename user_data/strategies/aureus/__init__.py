"""AUREUS — package métier (étape 1 : socle).

Modules purs (stdlib uniquement), sans dépendance Freqtrade :
- config_schema : validation fail-fast de la configuration
- boundary      : frontière Decimal ⇄ float et quantization
- state         : persistence JSON atomique de l'état global
- diagnostics   : événements JSONL structurés
"""

__version__ = "0.1.0"
