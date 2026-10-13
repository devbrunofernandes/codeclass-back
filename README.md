# CodeClass Backend

Backend da plataforma CodeClass para ensino e avaliação prática de programação, construído com FastAPI, PostgreSQL, Supabase e Google Gemini.

---

## 🛠️ Pré-requisitos

* [Python 3.14+](https://www.python.org/)
* [uv](https://docs.astral.sh/uv/)
* [Docker](https://www.docker.com/) (com serviço ativo)
* [Supabase CLI](https://supabase.com/docs/guides/cli) (ou `npx supabase` via Node.js 18+)
* [GNU Make](https://www.gnu.org/software/make/)

---

## 🚀 Instalação e Configuração

1. **Configurar variáveis de ambiente:**
   ```bash
   cp .env.example .env
   ```

2. **Instalar dependências com o `uv`:**
   ```bash
   uv sync --all-groups
   ```

---

## 💻 Comandos Úteis (Makefile)

O ciclo de vida local é gerenciado via `Makefile`:

* **Iniciar todo o ambiente local (Supabase, runner Piston, migrações, seed e API):**
  ```bash
  make start
  ```
  *A API estará disponível em `http://localhost:8000/docs` (logs em `/tmp/codeclass_api.log`).*

* **Parar a API e os containers:**
  ```bash
  make stop
  ```

* **Executar linter, tipagem e testes (`ruff`, `mypy`, `pytest`):**
  ```bash
  make test
  ```

* **Resetar banco de dados local, reaplicar migrações/seed e reiniciar a API:**
  ```bash
  make reset
  ```

### Gerenciamento de dependências:

* **Adicionar dependência de produção:**
  ```bash
  uv add <nome-do-pacote>
  ```

* **Adicionar dependência de desenvolvimento:**
  ```bash
  uv add --dev <nome-do-pacote>
  ```

---

## Testes por camada

Os testes unitários executam sem PostgreSQL, Supabase ou rede:

```bash
uv run pytest tests/unit -q
```

Os testes de domínio não carregam a aplicação HTTP nem provedores externos. As
fixtures reutilizáveis ficam em `tests/fixtures/` e são registradas em
`tests/conftest.py`. Tentativas de rede nos unitários falham imediatamente. Os
testes com SDKs mockados ou arquivos em memória também substituem o executor de
threads; eles verificam o resultado e os erros dessas operações, sem validar o
executor real.

Os testes de API e integração usam PostgreSQL real. Inicie o ambiente com
`make start` antes de executar `make test` ou a validação com cobertura:

```bash
uv run pytest --cov=app --cov-report=term-missing
```

A limpeza do banco acontece antes e depois de cada teste nesses dois escopos,
inclusive em caso de falha. As fixtures `db_session` e `async_client` dependem
explicitamente dessa limpeza. Testes de serviços que verificam persistência
ficam em `tests/integration/services/`; as jornadas completas continuam em
`tests/integration/test_*_lifecycle_integration.py`.

---

## 🗄️ Banco de Dados e Migrações (Alembic)

* **Criar nova migração:**
  ```bash
  uv run alembic revision --autogenerate -m "descreva a alteracao"
  ```

* **Aplicar migrações pendentes manualmente:**
  ```bash
  uv run alembic upgrade head
  ```

* **Reverter a última migração:**
  ```bash
  uv run alembic downgrade -1
  ```
