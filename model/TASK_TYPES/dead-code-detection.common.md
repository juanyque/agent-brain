# Dead Code Detection — task-type guide

Análisis sistemático para identificar código muerto en un proyecto con el mínimo de falsos positivos — funciones/clases/módulos nunca referenciados, imports no consumidos, código inalcanzable, tests inválidos.

## When this applies

- Pre-upgrade de herramientas base (Python, frameworks, dependencias mayores) donde quieres reducir el surface area antes del salto.
- Auditoría periódica del codebase (housekeeping).
- Cuando sospechas que un módulo/feature ha sido superseded pero el código sigue ahí.
- Preparación de un refactor mayor — necesitas saber qué se puede eliminar primero.

## Before starting

- [ ] Identificar lenguajes y frameworks del proyecto.
- [ ] Localizar herramientas de análisis estático ya configuradas (`pylint`, `flake8`, `eslint`, `rubocop`, `detekt`, etc.) y sus configs.
- [ ] Definir alcance: proyecto entero / módulo concreto / DT específico.
- [ ] Decidir carpeta WIP para findings (e.g. `~/WIP/<project>_dead_code/`).

## Process

1. **Exploración inicial** — entender estructura del proyecto: lenguajes, frameworks, herramientas de lint existentes, convenciones de packaging.
2. **Ejecutar herramientas existentes** — pylint/flake8/eslint/etc. con la config del proyecto. Capturar output crudo.
3. **Análisis manual dirigido** para patrones que las herramientas automáticas suelen perder:
   - Feature flags / toggles hardcodeados en `False`
   - Tests con `skip`/`xfail`/`pending` cuyo motivo referencia tickets ya cerrados
   - Módulos completos sin ningún inbound import
   - Versiones hardcoded ya superadas (e.g. `if PYTHON_VERSION < (3, 8)` cuando minimum es 3.12)
4. **Validación cruzada** — para cada hallazgo, confirma que no hay uso indirecto antes de marcarlo:
   - Metaprogramación / `getattr` / reflection
   - `__all__` exports
   - Decoradores dinámicos
   - Plugins / entry points
   - Test fixtures vía discovery
5. **Consolidar** el reporte siguiendo el note shape.

## Important limitations

- **Imports en type hints son válidos** — no marcar como sin uso. Verificar si un import aparece en `from __future__ import annotations` context o type-only.
- **No marcar código usado via metaprogramación** (`getattr`, `__all__`, decoradores dinámicos, reflection) sin verificación explícita.
- **Un módulo "sin uso interno" puede exportarse para uso externo** — confirmar antes de marcarlo.
- **Confianza explícita por hallazgo** es esencial — evita lista enorme de falsos positivos.

## Note shape (suggested for deliverable)

```markdown
# Dead Code Analysis — <project> (YYYY-MM-DD)

## Resumen ejecutivo
- Total hallazgos por categoría
- Estimación del impacto (líneas de código eliminables)

## Hallazgos por categoría

### 1. Imports sin uso
Per hallazgo:
- **Archivo**: ruta relativa + línea
- **Tipo**: `import sin uso`
- **Descripción**: qué es y por qué es muerto
- **Confianza**: Alta | Media | Baja (justifica si Media/Baja)
- **Acción recomendada**: eliminar | investigar más | ignorar (con motivo)

### 2. Símbolos definidos pero nunca usados
### 3. Código inalcanzable
### 4. Tests a revisar (skips, inválidos, triviales)
### 5. Módulos/archivos completos candidatos a eliminación

## Falsos positivos excluidos
Hallazgos que inicialmente parecían muertos pero se descartaron, con razón explícita.
```

## Control de calidad del reporte

Antes de entregar, verificar:
- Cada hallazgo tiene archivo + línea **verificada** (no aproximada).
- Ningún hallazgo de confianza Alta depende de análisis dinámico sin verificación estática.
- Tests "inválidos" tienen justificación explícita de por qué ya no aplican.
- Se distingue claramente "seguro de eliminar" vs "requiere investigación".
- No hay advertencias sobre código en `__all__` o que podría usarse externamente sin haberlo verificado.
- Las herramientas de lint del proyecto se ejecutaron y su output está integrado.

## Common gotchas

- **Saltar la sección de falsos positivos** → entrega menos confianza en el reporte; obliga al usuario a reverificar todo.
- **Empezar análisis manual sin ejecutar las herramientas existentes** → duplica trabajo + pierde el baseline que el proyecto ya tiene.
- **Marcar todo "Alta confianza" sin más** → frecuente con LLMs; forzar gradación realista (Media/Baja con razón).
- **Olvidar tests skip con motivo stale** → categoría 4 es donde más wins fáciles aparecen.
- **Tratar el reporte como "lista para borrar"** → el reporte es para revisar y decidir, no para ejecutar mecánicamente.

## References

- Lint configs del proyecto target (`.flake8`, `pyproject.toml`, `eslint.config.js`, `detekt.yml`, etc.).
- Related task-type: [[test-coverage-analysis]] — complementario. Coverage gaps + dead code suelen revelarse mutuamente.
- Memoria forward-looking: `step-by-step-implementation` — para procesar el reporte resultante incrementalmente.
