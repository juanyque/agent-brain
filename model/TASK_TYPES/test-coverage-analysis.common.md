# Test Coverage Analysis — task-type guide

Análisis de cobertura de tests de un proyecto para decidir qué tests crear, rehacer o eliminar — típicamente como preparación de un upgrade sensible (Python version, MySQL version, dependency major bump).

## When this applies

- Antes de un upgrade significativo donde necesitas cobertura sólida para validar regresiones (Python 3.x → 3.y, MySQL N → N+1, framework major version, etc.).
- Auditoría de salud del codebase — duda fundada sobre la calidad de cobertura.
- Preparación de un refactor mayor.
- Onboarding a un proyecto nuevo y quieres entender qué tests existen vs qué falta.

## Before starting

- [ ] Identificar proyecto/DT concreto (no "el repo entero" — define alcance).
- [ ] Confirmar herramientas de coverage del proyecto (`pytest-cov`, `coverage.py`, `kover`, etc.) y comando para ejecutarlas.
- [ ] Comprobar si existe baseline de coverage previo (porcentaje histórico, thresholds en CI).
- [ ] Decidir carpeta WIP para consolidar análisis (e.g. `~/WIP/<project>_tests/`).
- [ ] Confirmar con el usuario: ¿alcance es solo unit tests, o también integration tests?

## Process

1. **Inventario de tests existentes** — número de tests, estructura (unit vs integration), convenciones (marcas, fixtures, mocking patterns).
2. **Coverage report contra código actual** — overall % + per-file/per-module. Capturar tabla cruda como baseline.
3. **Identificar gaps críticos**:
   - Módulos core sin coverage o por debajo de threshold razonable.
   - Branches críticos (error handling, edge cases) sin tests.
   - Código nuevo sin tests asociados (PRs recientes sin updates en tests/).
4. **Identificar tests obsoletos o triviales**:
   - Tests skipeados con razón referenciando tickets cerrados.
   - Tests sobre código eliminado.
   - Asserts triviales que siempre pasan (`assertTrue(True)`, etc.).
   - Tests con mocks excesivos que ya no validan comportamiento real.
5. **Decidir por gap** (no presuponer "más tests es mejor"): crear nuevo / rehacer / eliminar / dejar como está. Justifica cada decisión.
6. **Consolidar** análisis + decisiones en MD docs en la carpeta WIP. Iterar por bloques pequeños — no intentar todo en un solo dump.

## Note shape (suggested deliverable)

Estructura sugerida para `~/WIP/<project>_tests/`:

```
<project>_tests/
├── 01-baseline.md          # Coverage actual, herramientas, comando, output crudo
├── 02-inventory.md         # Tests existentes, organización, conventions
├── 03-gaps-critical.md     # Módulos/branches con gaps importantes
├── 04-obsolete-tests.md    # Skips stale, triviales, sobre código removido
├── 05-decisions.md         # Por gap: create/redo/drop/keep + razón
└── 06-action-plan.md       # Plan ordenado para abordar decisiones
```

## Common gotchas

- **Coverage % alto NO implica tests útiles** — mocks excesivos inflan la métrica sin validar comportamiento. Revisar calidad, no solo cantidad.
- **Tests de integración no se computan igual** que unitarios — algunos coverage tools excluyen tests de integración por default, otros los incluyen pero con cálculo distinto. Verificar config antes de comparar números.
- **Cobertura de branches** (`branch coverage`) es más útil que cobertura de líneas para detectar error-handling sin tests.
- **Tests con `skip` antiguo**: si el motivo del skip referencia un ticket, comprobar estado del ticket en Jira. Si está cerrado/won't-fix, el skip es candidato a borrado o a recovery.
- **Mocks que mockean lo equivocado**: tests que mockean la función que se está testeando (en vez de las deps externas) — passing pero sin valor.
- **No mezclar coverage analysis con refactor**: el análisis es read-only. Cualquier cambio (añadir test, borrar test) es un PR separado posterior.

## References

- Tests del proyecto target (`<project>/tests/` o equivalente).
- Coverage config del proyecto (en `pyproject.toml`, `pytest.ini`, `build.gradle.kts` con kover, etc.).
- Related task-types: [[dead-code-detection]] — complementario. Tests sobre código muerto = candidatos obvios a borrar; código sin tests + sin uso = candidato a dead code.
- Related task-type: [[migration-task]] — el análisis de coverage es frecuentemente un pre-requisito de migration tasks grandes (e.g. Python version upgrade).
