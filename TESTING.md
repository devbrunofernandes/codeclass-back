# Testes do CodeClass Backend

Este guia descreve como validar o backend e executar os testes por camada.
Execute os comandos a partir de `codeclass-back/`. Para instalar as dependências,
configurar o `.env` e iniciar o projeto, consulte o [README.md](README.md).

## Validação padrão

Com o ambiente preparado e a infraestrutura iniciada por `make start`, execute:

```bash
make test
```

Esse comando executa, em sequência, `ruff check .`, `mypy app` e `pytest -v`.
Os testes marcados como `live` ficam excluídos da execução padrão.

Para formatar o código antes da validação:

```bash
uv run ruff format .
```

Para verificar a cobertura mínima de 85% em `app/`:

```bash
uv run pytest --cov=app --cov-report=term-missing --cov-fail-under=85
```

## Preparação do banco de testes

Os testes de API e integração apagam as tabelas da aplicação antes e depois de
cada teste. Use um ambiente dedicado, sem dados que devam ser preservados,
e não execute essas suítes em paralelo no mesmo banco.

## Testes por camada

A organização separa a lógica central das implementações dos provedores:

```text
tests/
├── unit/                    # Domínio, serviços e infraestrutura genérica
│   ├── infrastructure/      # Componentes de app/infrastructure/
│   │   └── providers/       # SDKs, fábricas e adaptadores específicos
│   └── testing/            # Fixtures, isolamento e suporte da suíte
├── api/                     # Contratos HTTP
├── integration/
│   ├── services/            # Persistência e serviços
│   ├── providers/           # Supabase Auth e PostgreSQL LISTEN/NOTIFY
│   └── live/                # Jornadas com os serviços reais configurados
└── fixtures/                # Fixtures e configuração dos provedores
```

A classificação segue a intenção do teste:

- Arquivos diretamente em `unit/infrastructure/`: comportamento genérico dos
  componentes de `app/infrastructure/`, como conexões, distribuição de mensagens,
  sockets com falha e rejeição de estratégias desconhecidas. Usam mocks dos
  contratos, sem importar adaptadores concretos.
- `unit/testing/`: funcionamento da própria suíte, incluindo fixtures, bloqueio
  de rede, isolamento do banco, seleção de mocks e restauração de dependências.
- `unit/infrastructure/providers/`: tradução de respostas, headers, SDKs,
  seleção de uma implementação pela fábrica e requisitos de credenciais de
  cada adaptador.
  O próprio adaptador ou sua configuração específica é o objeto da verificação.

Usar um provedor concreto apenas para preparar um teste genérico não justifica
classificá-lo em `providers/`: substitua essa dependência por um mock do contrato.
Uma operação com nome genérico, como upload, pode permanecer em `providers/`
quando a intenção for verificar como um adaptador específico a executa.

Os testes unitários, inclusive os dos adaptadores, executam sem rede:

```bash
make test-unit                              # lógica central e adaptadores
uv run pytest tests/unit -q                  # todos os unitários
uv run pytest tests/unit --ignore=tests/unit/infrastructure/providers -q  # somente lógica central
uv run pytest tests/unit/infrastructure/providers -q        # somente adaptadores
uv run pytest tests/unit/testing -q          # somente suporte da suíte
```

`tests/unit/infrastructure/providers/` testa detalhes dos SDKs e a tradução das
respostas externas para os contratos da aplicação, com I/O mockado. O bloqueio
de rede é herdado de `tests/unit/conftest.py`.

Os testes de domínio não carregam a aplicação HTTP nem provedores externos. As
fixtures reutilizáveis ficam em `tests/fixtures/` e são registradas em
`tests/conftest.py`. Tentativas de rede nos unitários falham imediatamente. Os
testes com SDKs mockados ou arquivos em memória também substituem o executor de
threads; eles verificam o resultado e os erros dessas operações, sem validar o
executor real.

Os testes de API e integração usam PostgreSQL real e exigem a infraestrutura
iniciada com `make start`. Para executar cada camada separadamente:

```bash
uv run pytest tests/api -q
make test-integration
```

`make test-integration` executa as integrações centrais e as integrações dos
provedores, excluindo `live`. Para executar somente os testes dos provedores
(unitários e integração com banco real):

```bash
make test-providers
```

As verificações específicas de tabelas `auth.users`, triggers e comunicação
entre brokers PostgreSQL ficam em `tests/integration/providers/`. Elas preservam
a validação dos detalhes dos adaptadores fora das jornadas centrais.

A limpeza do banco acontece antes e depois de cada teste nesses dois escopos,
inclusive em caso de falha. As fixtures `db_session` e `async_client` dependem
explicitamente dessa limpeza. Testes de serviços que verificam persistência
ficam em `tests/integration/services/`; as jornadas completas continuam em
`tests/integration/test_*_lifecycle_integration.py`.

## Integração com serviços reais (`live`)

Os testes live ficam em `tests/integration/live/` e usam os serviços configurados
na aplicação. Os comandos também podem ser executados diretamente com
`uv run pytest tests/integration/live -m live -v`.

A execução padrão exclui `live`. Ela usa PostgreSQL real e mantém IA/Runner
simulados. Os testes live ativam somente o serviço indicado em
`@pytest.mark.live("serviço")`; por exemplo, Storage live não consome IA real.
Auth já possui integrações reais na suíte padrão; a jornada live acrescenta
alteração de nome/senha, refresh, revogação e exclusão pelo contrato público da
aplicação. As consultas ao schema interno do Supabase ficam na suíte de provedores.

```bash
make test-live                         # todos os serviços reais
make test-live LIVE_SERVICE=runner     # accepted, wrong answer, runtime error, timeout
make test-live LIVE_SERVICE=storage    # upload, listagem, download e remoção reais
make test-live LIVE_SERVICE=auth
make test-live LIVE_SERVICE=ai
make test-live LIVE_SERVICE=chat       # TCP/WebSocket com o broker configurado
```

O bucket privado `classroom-materials` é provisionado pelo seed de `make start`.
As configurações são lidas do ambiente ou `.env`, sem imprimir credenciais:

| Serviço | Configuração obrigatória adicional ao `DATABASE_URL` |
| --- | --- |
| IA | `AI_API_KEY`; configure `AI_PROVIDER` e `AI_MODEL` compatíveis |
| Runner | `RUNNER_API_URL`; `RUNNER_API_KEY` para Judge0; Piston local dispensa chave |
| Storage/Auth | `SUPABASE_URL` e `SUPABASE_KEY` com permissões de serviço |
| Chat | `PUBSUB_BROKER` seleciona a estratégia; PostgreSQL exige banco acessível |

Selecionar um serviço live sem a configuração obrigatória causa erro de coleta,
sem `skip` silencioso. Provedor indisponível ou credencial inválida causa falha.
Storage usa nome único e limpeza em `finally`; Auth usa usuários únicos e a
limpeza das fixtures. WebSockets têm prazo máximo e servidor em porta efêmera.
IA verifica estrutura e persistência, sem exigir texto ou nota exatos.

Os testes de provedores herdam automaticamente o isolamento de sua camada:
unitários sem rede e integrações com limpeza de banco.

A seleção dos testes live conhece o serviço (`ai`, `runner`, `storage`, `auth`,
`chat`). As diferenças de credenciais entre adaptadores ficam isoladas em
`tests/fixtures/providers.py`; a validação e seleção genéricas ficam em
`tests/fixtures/live.py`. O Chat resolve o broker pela fábrica da
aplicação; a integração específica de LISTEN/NOTIFY permanece na suíte dos
provedores.

## Compatibilidade do índice do Supabase Storage local

O upload real pode falhar com HTTP 500 e SQLSTATE `42P10` se a instalação local
mantiver `storage.idx_objects_current_version` sem `COLLATE "C"`. O Storage usa
essa collation em seu `ON CONFLICT`, conforme a migração interna 0066.

O reparo está em `supabase/seed.sql`: cria o índice compatível antes de substituir
o antigo, preserva o nome esperado pelo Storage e executa tudo em uma transação.
Se o índice já estiver correto, ele não é reconstruído. Definições inesperadas
interrompem a operação para evitar sobrescrever contratos de outras versões.
O reparo não altera registros ou arquivos, mas bloqueia escritas na tabela durante
a reconstrução do índice.

Na primeira correção, use uma conexão administrativa **local** com permissão
para manter tanto as tabelas públicas do seed quanto `storage.objects`.
O papel `postgres` do Supabase local pode não ter permissão para reconstruir
índices pertencentes a `supabase_storage_admin`. Configure
`STORAGE_REPAIR_DB_URL` com uma conexão administrativa para o banco local e aplique
pelo Supabase CLI a partir de `codeclass-back/`:

```bash
npx supabase db query --db-url "$STORAGE_REPAIR_DB_URL" -f supabase/seed.sql
```

Depois da correção, o comando local padrão pode ser repetido normalmente, sem
reconstruir o índice ou exigir novas permissões:

```bash
npx supabase db query --local -f supabase/seed.sql
uv run pytest tests/integration/providers/test_supabase_storage_schema_integration.py -q
make test-live LIVE_SERVICE=storage
```

O teste de schema usa `EXPLAIN` para conferir a inferência do índice pelo
`ON CONFLICT` sem inserir objetos. A jornada live verifica o upload, a listagem,
o download com conteúdo idêntico e a exclusão reais.
