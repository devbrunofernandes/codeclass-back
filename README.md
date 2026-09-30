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
