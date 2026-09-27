.PHONY: start stop test reset

start:
	@echo "--> Iniciando infraestrutura do Supabase..."
	@npx supabase start
	@echo "--> Iniciando executor de código local (Piston)..."
	@docker start codeclass-runner 2>/dev/null || (docker run -d --privileged -v codeclass_piston:/piston --name codeclass-runner -p 2000:2000 ghcr.io/engineer-man/piston && sleep 2 && curl -s -X POST http://localhost:2000/api/v2/packages -H "Content-Type: application/json" -d '{"language": "python", "version": "3.12.0"}' >/dev/null 2>&1)
	@echo "--> Aplicando migrações do Alembic..."
	@uv run alembic upgrade head
	@echo "--> Aplicando seed do Supabase..."
	@npx supabase db query --local -f supabase/seed.sql
	@echo "--> Iniciando FastAPI em background..."
	@fuser -k 8000/tcp 2>/dev/null || true
	@setsid uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload > /tmp/codeclass_api.log 2>&1 &
	@sleep 1
	@echo "Ambiente pronto em http://localhost:8000/docs (logs em /tmp/codeclass_api.log)"

stop:
	@echo "--> Encerrando FastAPI..."
	@fuser -k 8000/tcp 2>/dev/null || true
	@echo "--> Encerrando executor de código local (Piston)..."
	@docker stop codeclass-runner 2>/dev/null || true
	@echo "--> Encerrando containers do Supabase..."
	@npx supabase stop
	@echo "Ambiente encerrado."

test:
	@echo "--> Executando linter (ruff check)..."
	@uv run ruff check .
	@echo "--> Executando checagem estática de tipos (mypy)..."
	@uv run mypy app
	@echo "--> Executando testes automatizados (pytest)..."
	@uv run pytest -v

reset:
	@echo "--> Encerrando FastAPI..."
	@fuser -k 8000/tcp 2>/dev/null || true
	@echo "--> Resetando banco de dados local do Supabase..."
	@npx supabase db reset --no-seed
	@$(MAKE) start
