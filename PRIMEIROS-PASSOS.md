# Primeiros passos

## 1. Extrair com os arquivos ocultos

```bash
unzip -o vzdr.zip
cd vzdr
ls -a          # tem que aparecer .specify, .vscode, .github, .gitignore, .env.example
./scripts/verificar-scaffold.sh
```

O `ls` normal **não mostra** os arquivos que começam com ponto. Se o `.specify/` não
estiver lá, o método inteiro está sem a constitution — extraia de novo.

## 2. Git

```bash
git config --global user.name "Seu Nome"
git config --global user.email "voce@informo.com.br"
git config --global init.defaultBranch main

git init && git add -A && git commit -m "scaffold inicial"
git branch -m main
```

Renomear o branch antes do primeiro commit falha em git mais antigo — commite primeiro.

## 3. Ambiente

```bash
apt update && apt install -y make python3-venv python3-pip git   # se faltar algo
./scripts/bootstrap.sh
```

Sem docker instalado, o `make db-up` não roda — e tudo bem. O PostgreSQL só é necessário
quando a `core-001` começar a persistir alguma coisa.

## 4. Sobre a versão de Python

**O agente é 3.9; o projeto não.** A restrição vem dos hypervisors, e lá só roda o
agente. O control plane — API, CLI, tudo o mais — roda em 3.11.

Na prática: `packages/agent` e `packages/core-domain` declaram `target-version = "py39"`
no próprio `pyproject.toml` e não podem usar sintaxe de 3.10+. O resto segue a raiz, em
`py311`.

A parte que é fácil esquecer: um pacote restrito não pode importar um que não seja. O
`tests/invariants/check_alvo_py39.py` falha o build se isso acontecer — senão a fronteira
seria documentação, não garantia. O porquê está em `docs/adr/0007-alvo-de-python-por-pacote.md`.

## 5. Spec Kit

```bash
uv tool install specify-cli --from git+https://github.com/github/spec-kit.git
specify init . --ai copilot        # ou claude, cursor, gemini...
```

A constitution já está escrita em `.specify/memory/constitution.md`. Não precisa rodar
`/speckit.constitution` — mas leia antes de começar, porque tudo herda dela.

## 6. A primeira feature

`specs/core-001-tenancy/spec.md` já está em rascunho. O fluxo:

1. Leia e ajuste o que não bate com o que você quer
2. `/speckit.clarify` — responda as perguntas do fim da spec
3. `/speckit.plan` — revise antes de seguir
4. `/speckit.tasks`
5. `/speckit.analyze`
6. `/speckit.implement` — **uma tarefa por vez**

## 7. Em paralelo, no cluster

A Fase 0 de medição não depende de código nenhum e dimensiona o projeto inteiro:

```bash
./scripts/censo-formatos.sh                        # em cada hypervisor
./scripts/medir-taxa-mudanca.sh <dominio> 300      # em 20-30 VMs, por 48h
```

E o teste ainda aberto: **o dirty bitmap sobrevive quando o VHI migra a VM de nó sozinho?**
Crie um checkpoint com dados, migre pelo OpenStack (nunca por `virsh`), e releia os bitmaps
no destino.

## 8. Trabalhando remoto

Você está desenvolvendo no servidor. Funciona, mas o mais confortável é abrir a pasta pelo
**VS Code Remote-SSH** da sua máquina — você ganha as extensões, o Copilot e o Spec Kit
rodando local, editando os arquivos remotos.

## Mapa

| Arquivo | Para quê |
| --- | --- |
| `AGENTS.md` | Instruções para o agente de IA. Ele lê isso sempre |
| `.specify/memory/constitution.md` | Os 13 princípios inegociáveis |
| `CONTRIBUTING.md` | O fluxo SDD e como fatiar o trabalho |
| `specs/README.md` | As 18 specs, na ordem, com dependências e marcos |
| `docs/00-visao.md` | O produto e a regra de ouro |
| `docs/01-arquitetura-dr.md` | O ciclo, os números validados e as 8 pegadinhas |
| `docs/02-plataforma.md` | Núcleo vs feature, conexões, eventos |
| `docs/03-roadmap.md` | Os 6 marcos com critério de saída |
| `docs/adr/` | Sete decisões já registradas |
| `tests/invariants/` | A CI falha se o domínio fizer IO, as fronteiras furarem, faltar tenant_id ou o fecho de 3.9 vazar |
| `scripts/` | Censo de formatos, medição de taxa de mudança, verificação do scaffold |
