"""Auditoria: quem fez o que, quando, em qual tenant."""

from vzdr.core.audit.registro import (
    PrincipalNaoEDePlataformaError,
    registrar,
    registrar_plataforma,
)

__all__ = [
    "PrincipalNaoEDePlataformaError",
    "registrar",
    "registrar_plataforma",
]
