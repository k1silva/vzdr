"""Hash de senha com scrypt da stdlib, e o algoritmo gravado em cada linha.

Zero dependencia: `hashlib.scrypt` ja esta na stdlib, e `argon2-cffi` e
extensao C para construir, auditar e fixar. A senha tambem nao e o elo fraco
deste sistema — o que vale a pena atacar aqui sao as credenciais OpenStack e o
rele, nao a senha de meia duzia de operadores.

## O que mantem a porta aberta

Cada linha guarda **algoritmo + parametros + salt**, nesta ordem:

    scrypt$ln=16,r=8,p=2$<salt em base64>

Quem valida le o algoritmo que a linha declara e NUNCA assume a politica
vigente. E o que faz adotar Argon2id depois ser aditivo: valida-se o hash
antigo pelo algoritmo dele e re-hasheia no proximo login bem-sucedido, que e o
unico momento em que a senha em claro existe.

Mas isso so vira migracao de verdade se alguem re-hashear. Ver
`precisa_de_rehash()` e o uso dela em `autenticacao.autenticar()`: sem o
re-hash no login, "e aditivo" e plano que nunca executa — os parametros ficam
gravados, ninguem migra, e em dois anos todo mundo continua no scrypt original.
Vale igual para subir `N` sem trocar de algoritmo, que e o caso mais provavel.

## maxmem nao e detalhe

`N=2^16` com `r=8` pede 64 MiB (`128 * N * r`), e o padrao `maxmem=0` do
`hashlib.scrypt` usa o limite do OpenSSL, da ordem de 32 MiB: levanta
`ValueError`. E a armadilha desta casa — teste com parametros pequenos passa,
producao com os reais quebra —, entao o `maxmem` e calculado dos parametros e
ha teste com os valores de politica, nao so com valores reduzidos.

## O custo e superficie de ataque

scrypt e memory-hard por construcao, e e dai que vem a resistencia a GPU. Mas
64 MiB por hash significa que um endpoint de login sem limite e negacao de
servico barata. O semaforo abaixo limita quantos hashes correm ao mesmo tempo;
o limite por IP e de `core-007`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
from dataclasses import dataclass

ALGORITMO = "scrypt"
TAMANHO_DO_SALT = 16
TAMANHO_DA_CHAVE = 64

#: Quantos hashes podem correr ao mesmo tempo. Cada um custa `memoria()` da
#: politica — com o padrao, 4 x 64 MiB.
LIMITE_DE_CONCORRENCIA = 4

_vagas = threading.BoundedSemaphore(LIMITE_DE_CONCORRENCIA)


class AlgoritmoDesconhecidoError(Exception):
    """A linha declara um algoritmo que este codigo nao sabe validar.

    Falha em vez de tentar com a politica vigente: cair no padrao transformaria
    "senha invalida" em "hash ilegivel" sem ninguem perceber.
    """


class ParametrosIlegiveisError(Exception):
    """`senha_params` fora do formato `algoritmo$parametros$salt`."""


@dataclass(frozen=True)
class Politica:
    """Parametros de custo. OWASP lista `N=2^17, r=8, p=1` como primeira
    escolha e `N=2^16, r=8, p=2` como equivalente imediato; a forma dos
    parametros e o custo `128 * N * r` vem da RFC 7914."""

    ln: int = 16  # log2(N)
    r: int = 8
    p: int = 2

    @property
    def n(self) -> int:
        return int(2**self.ln)

    def memoria(self) -> int:
        """Quanto o OpenSSL precisa poder alocar, em bytes.

        Medido, nao decorado: com `N=2^16, r=8, p=2` isto da 64 MiB e passa,
        enquanto o padrao do `hashlib` recusa.
        """
        return 128 * self.r * (self.n + self.p + 2)

    def rotulo(self) -> str:
        return f"ln={self.ln},r={self.r},p={self.p}"


POLITICA = Politica()


def _derivar(senha: str, salt: bytes, politica: Politica) -> bytes:
    with _vagas:
        return hashlib.scrypt(
            senha.encode("utf-8"),
            salt=salt,
            n=politica.n,
            r=politica.r,
            p=politica.p,
            maxmem=politica.memoria(),
            dklen=TAMANHO_DA_CHAVE,
        )


def _ler_parametros(senha_params: str) -> tuple[Politica, bytes]:
    partes = senha_params.split("$")
    if len(partes) != 3:
        raise ParametrosIlegiveisError(
            f"esperado 'algoritmo$parametros$salt', veio {senha_params!r}"
        )
    algoritmo, rotulo, salt = partes
    if algoritmo != ALGORITMO:
        raise AlgoritmoDesconhecidoError(
            f"linha declara {algoritmo!r}, que este codigo nao valida. "
            f"Nao caio na politica vigente: isso transformaria hash ilegivel "
            f"em 'senha invalida'."
        )
    try:
        campos = dict(par.split("=", 1) for par in rotulo.split(","))
        politica = Politica(ln=int(campos["ln"]), r=int(campos["r"]), p=int(campos["p"]))
    except (KeyError, ValueError) as erro:
        raise ParametrosIlegiveisError(f"parametros ilegiveis em {rotulo!r}") from erro
    return politica, base64.b64decode(salt)


def hashear(senha: str, politica: Politica = POLITICA) -> tuple[str, str]:
    """Devolve `(senha_hash, senha_params)`."""
    salt = secrets.token_bytes(TAMANHO_DO_SALT)
    chave = _derivar(senha, salt, politica)
    params = f"{ALGORITMO}${politica.rotulo()}${base64.b64encode(salt).decode()}"
    return base64.b64encode(chave).decode(), params


def verificar(senha: str, senha_hash: str, senha_params: str) -> bool:
    """Valida pelo algoritmo que a LINHA declara, nunca pela politica vigente."""
    politica, salt = _ler_parametros(senha_params)
    esperado = base64.b64decode(senha_hash)
    return hmac.compare_digest(_derivar(senha, salt, politica), esperado)


def precisa_de_rehash(senha_params: str, politica: Politica = POLITICA) -> bool:
    """Se a linha esta defasada em relacao a politica vigente.

    Quem chama isto e o login bem-sucedido. E o unico momento em que a senha em
    claro existe, e por isso o unico momento em que a migracao pode acontecer.
    """
    try:
        gravada, _ = _ler_parametros(senha_params)
    except (AlgoritmoDesconhecidoError, ParametrosIlegiveisError):
        # Nao da para re-hashear o que nao da para validar; quem valida decide.
        return False
    return gravada != politica
