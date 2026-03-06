# SKILLS.md

## Project Overview

- **Language:** python
- **Build tool:** <!-- TODO: e.g. pip, maven, gradle, npm -->
- **Description:** <!-- TODO: one-line project description -->

## Tech Stack

**Language:** python | **Test framework:** pytest_or_unittest

## Repository Layout

```
.claude/
  settings.local.json
deploy/
  ecs-task-definition.json
examples/
  bdd_spec_example.json
scripts/
  run_grep.py
  run_tests.py
  verify_context_pipeline.py
src/
  agent/
    __init__.py
    activity.py
    ai_utils.py
    analyzer.py
    context.py
    gcc.py
    knowledge.py
    knowledge_generator.py
    plan.py
    plan_display.py
    tools.py
    tracing.py
  api/
    routes/

    __init__.py
    app.py
    schemas.py
    websocket.py
  bdd/
    __init__.py
    output_parser.py
    prompt_builder.py
    service_spec.py
    servlet_discovery.py
  code/
    __init__.py
    analyzer.py
    executor.py
    search.py
    testing_strategies.py
  code_index/
    __init__.py
    entity_embeddings.py
    graph_builder.py
    hierarchy.py
    import_resolver.py
    property_index.py
    storage.py
    symbol_table.py
    tools.py
    verifier.py
  consciousness/
    __init__.py
    core.py
    opensearch.py
  context/
    call_graph/

    enrichers/

    __init__.py
    base.py
    pipeline.py
  data/
    __init__.py
    database.py
    models.py
    repositories.py
    store_adapters.py
  embeddings/
    __init__.py
  jira/
    __init__.py
    bitbucket_bridge.py
    client.py
    session.py
  platform/
    __init__.py
    bitbucket_server.py
    git_ops.py
    platform_client.py
    pr_platform.py
    reference_pr.py
  services/
    __init__.py
    agent_service.py
    cache.py
    config_service.py
    jira_run_service.py
    jira_runner.py
    jira_service.py
    orc
... (trimmed)
```

## Important Files

| File | Key symbols / purpose |
|------|----------------------|
| `src/api/app.py` | <!-- TODO: describe --> |
| `tests/test_llm_usage_stats.py` | <!-- TODO: describe --> |
| `tests/test_resiliency.py` | <!-- TODO: describe --> |
| `tests/test_repo_knowledge.py` | <!-- TODO: describe --> |
| `tests/test_llm_client_resiliency.py` | <!-- TODO: describe --> |
| `tests/test_startup_validator.py` | <!-- TODO: describe --> |
| `tests/test_services.py` | <!-- TODO: describe --> |
| `tests/test_code_index_chunking.py` | <!-- TODO: describe --> |

## Coding Conventions

- **Naming style:** snake_case
- **Formatting/linting:** <!-- TODO: e.g. black, ruff, prettier, checkstyle -->
- **Import ordering:** <!-- TODO: e.g. isort, stdlib-first -->

## Testing

- **Framework:** pytest_or_unittest
- **Run tests:** <!-- TODO: e.g. pytest tests/, mvn test -->
- **Coverage:** <!-- TODO: e.g. pytest --cov=src -->