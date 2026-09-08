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
