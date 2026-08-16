# Conversational Document Assistant

Guide users step-by-step from raw requirements to generated, printable documents without hardcoding rigid vault paths or assuming a single environment structure.

## Core Design Principles

1. **Agnostic & Relative Discovery**:
   - Do not hardcode absolute vault paths.
   - Look for active projects in the workspace work-in-progress area (e.g., `WIP/`, `projects/`, or root).
   - If not found in work areas, look in archive/memory stores (e.g., `MEMORY/`, `archive/`).
   - If still not found or ambiguous, ask the user for the target folder path.
2. **Deliverables Location Flexibility**:
   - Write deliverables (PDF, HTML) to the configured output area (e.g., `OUTBOX/`, `dist/`, `exports/`, or user-specified downloads).
   - Keep canonical Markdown and structured YAML data strictly inside the project folder.
3. **Deterministic Preflight Before Questioning**:
   - When a specific document is requested, run the document preflight to obtain the exact missing fields (`report_version: 0.1.0`).
   - Never hallucinate, guess, or invent legal or personal data.
   - Group missing data into clear, human-friendly conversational prompts.
   - Persist confirmed values immediately into `data/project-data.yaml`.

---

## 4-Step Conversational Interaction Model

```
User Intent ("Gestionar nuevo alquiler en Canarias 5 5-E")
   │
   ▼
[Step 1: Project Resolution]
   ├─ Check WIP/ / projects/
   ├─ Check MEMORY/ / archive/
   └─ If not found: initialize new project or ask path
   │
   ▼
[Step 2: Document Family Presentation]
   ├─ 1. Reserva (reservation)
   ├─ 2. Contrato de Arrendamiento (lease)
   ├─ 3. Inventario y Llaves (inventory)
   ├─ 4. Autorización de Acceso Previo (access-license)
   └─ 5. Resolución y Liquidación (termination)
   │
   ▼
[Step 3: Missing Data Interview]
   ├─ Run preflight for selected document
   ├─ If missing required data: prompt user in batches
   └─ Update data/project-data.yaml iteratively
   │
   ▼
[Step 4: Output Generation & Delivery]
   ├─ Render Markdown & PDF via pandoc/weasyprint
   ├─ Save PDF into output queue (e.g. OUTBOX/ or exports/)
   └─ Present result with clickable links
```

---

## Step 1: Project Discovery & Initialization

When the user mentions starting or continuing a project:
1. Search the workspace directories:
   - Current active directory or `WIP/<project-name>`
   - Long-term memory storage `MEMORY/<project-name>`
2. If creating a new project:
   - Create `project.yaml` (opaque descriptor compliant with `project-descriptor.schema.json`).
   - Create `data/project-data.yaml` inheriting standard defaults (e.g. `defaults_profile: residential-standard`).
   - If inside an Obsidian vault, optionally initialize a tracking note `*.gestor-documental.md`.

---

## Step 2: Document Family Lifecycle

Present the user with the available documents for the project type:

### For `residential-lease`:
| Document | Purpose | Key Data Requirements |
|---|---|---|
| **Reserva** (`reservation`) | Block property, set signal deposit and non-payment insurance conditions. | Signal amount, payment deadline, contract deadline, insurance status. |
| **Arrendamiento** (`lease`) | Canonical lease contract with full numbered clauses (1 to 10). | Landlord & tenant identities, start & signature dates, monthly rent, deposit & guarantee, bank IBAN. |
| **Inventario** (`inventory`) | Photographic inventory, key handover, and meter readings. | Rooms with item lists & photo paths, keys (portal, dwelling, mailbox), utility meter readings. |
| **Acceso Previo** (`access-license`) | Temporary pre-lease access for moving/furnishing without rent accrual. | Access window (from/to), keys delivery date. |
| **Resolución** (`termination`) | Mutual lease termination, key return, damage check, and financial settlement. | Termination effective date, keys returned, compensation amount/reason, deposit refund balance. |

---

## Step 3: Interactive Interview (Preflight-Driven)

When the user asks to generate a document (e.g., *"Quiero el contrato de arrendamiento"* o *"Quiero la resolución de contrato"*):
1. Run preflight to identify missing paths.
2. Formulate concise, grouped questions categorized logically:
   - **Partes**: Nombres completos, tipos de documento (`dni`, `nie`, `passport`), números y domicilios de notificación.
   - **Condiciones Económicas**: Renta mensual, fianza, garantía adicional e IBAN de cobro.
   - **Fechas Clave**: Fecha de firma (entrega de llaves), fecha de inicio de arriendo o fecha efectiva de resolución.
3. **Manejo de Resoluciones y Liquidaciones**:
   - Preguntar la **fecha acordada de resolución**. Si el usuario pide un modelo en blanco, utilizar líneas `__________` para rellenar in situ.
   - Si se proporciona una fecha concreta, el asistente aplica las reglas legales y contractuales (Cláusula Novena y Art. 11 LAU) y **explica de dónde salen los números**:
     - **Periodo Obligatorio (primeros 6 meses)**: Si la salida se produce antes de cumplir los 6 meses mínimos obligatorios (p. ej. el 30/08/2026 cuando el contrato empezó el 16/08/2026), no es un desistimiento legal ordinario sino una resolución anticipada o incumplimiento de permanencia, cuantificando las rentas pendientes de los meses obligatorios o la penalización pactada.
     - **Desistimiento Ordinario (meses 6 a 12 de la 1ª anualidad)**: Con 1 mes de preaviso, indemnización proporcional a 1 mensualidad por año restante de contrato.
     - **Desistimiento a partir del 2º año**: Salida libre con 1 mes de preaviso sin indemnización.
     - **Liquidación Neta de Garantías**: Descuento transparente de la indemnización sobre las garantías depositadas (fianza + garantía adicional), mostrando el saldo final a devolver.
4. Save responses directly to `data/project-data.yaml`.


---

## Step 4: Deterministic Generation & Delivery

1. Execute the renderer script targeting the chosen template:
   ```bash
   uv run scripts/render_document.py <template-path> <data-path> <output-pdf-path> --replace
   ```
2. The deliverable is placed in the designated workspace output area (e.g. `OUTBOX/` or `exports/<project-id>/`).
3. The assistant replies concisely, linking to the generated PDF and Markdown, and summarizing the next available documents in the lifecycle.
