# CodeClass Backend

Backend da plataforma CodeClass para ensino e avaliação prática de programação, construído com FastAPI, PostgreSQL, Supabase e Google Gemini.

---

## 🛠️ Pré-requisitos

* [Python 3.14+](https://www.python.org/)
* [uv](https://docs.astral.sh/uv/)
---

## 🚀 Instalação e Configuração

### 1. Instalar o `uv`

Caso ainda não tenha o `uv` instalado:

**Linux / macOS:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

---

### 2. Clonar o repositório e sincronizar dependências

Clone o repositório e navegue até a pasta:
```bash
cd codeclass-back
```

Sincronize as dependências do projeto (o `uv` criará o ambiente virtual `.venv` e instalará as versões exatas do `uv.lock` automaticamente):
```bash
uv sync
```

Para instalar incluindo as dependências de desenvolvimento e testes:
```bash
uv sync --all-groups
```

---

## 💻 Comandos Úteis

* **Executar a API em modo de desenvolvimento:**
  ```bash
  uv run uvicorn app.main:app --reload
  ```

* **Rodar os testes automatizados:**
  ```bash
  uv run pytest
  ```

* **Adicionar uma nova dependência de produção:**
  ```bash
  uv add <nome-do-pacote>
  ```

* **Adicionar uma dependência de desenvolvimento:**
  ```bash
  uv add --dev <nome-do-pacote>
  ```

---

## 🗄️ Banco de Dados e Migrações (Alembic)

O projeto utiliza o **Alembic** para versionamento e controle de migrações do PostgreSQL.

### Como funciona

* **`alembic/versions/`:** Guarda o histórico de migrações (scripts com `upgrade()` e `downgrade()`). Esses arquivos são versionados no Git.
* **`alembic/env.py`:** Conecta ao banco usando a `DATABASE_URL` do `.env` e compara os modelos SQLAlchemy (`Base.metadata`) com o banco real.

### Fluxo de trabalho com o banco

1. **Configurar variáveis de ambiente:**
   Copie o arquivo de exemplo e preencha sua string de conexão:
   ```bash
   cp .env.example .env
   ```

2. **Aplicar as migrações no banco (atualizar banco local):**
   Toda vez que você puxar código novo do Git, aplique as migrações pendentes:
   ```bash
   uv run alembic upgrade head
   ```

3. **Criar uma nova migração (após alterar/criar modelos SQLAlchemy):**
   ```bash
   uv run alembic revision --autogenerate -m "descreva a alteracao"
   ```
   *Um novo arquivo será gerado em `alembic/versions/`. Revise o código gerado antes de commitar.*

4. **Reverter a última migração (se necessário):**
   ```bash
   uv run alembic downgrade -1
   ```

