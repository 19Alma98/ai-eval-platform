# Metrics sets (versioned, reusable)

Date: 2026-10-05

## Problem

Test sets are named, versioned, and selected per experiment. Metrics are not: each project has one `MetricsPack` (`metrics_packs.entries` JSONB). Experiments do not store which metrics to use; scoring always uses the project pack (or an ad-hoc evaluator list).

Operators need several reusable metric bundles (for example RAG-strict vs RAG-latency) and the ability to pin a default on an experiment while overriding it for a single score run.

## Goals

- Multiple versioned metric sets per project (`name` + `version`), selectable like datasets.
- Experiment stores an optional default set; scoring can override for that run and optionally persist the override.
- Project-level fallback remains: if the experiment has no set, score with the project default set (today’s pack).
- Persist one metric per row. Seed rows on the project default set are marked `is_default` and cannot be deleted.
- Keep `/metrics-pack` as an alias of the project default set so existing UI and clients keep working.

## Non-goals

- Snapshotting entry payloads onto the experiment row.
- Merging `Evaluator` into metric-set entries (evaluators stay the executable implementations).
- Changing compare rules (still same `dataset_id`; scores still join on evaluator name / kind).
- Making the project default set deletable or replacing it with “no fallback”.

## Current state

- `metrics_packs`: one row per project, `entries` JSONB. Each entry has `kind`, `enabled`, `threshold`, `config`, `evaluator_id`, `removable`.
- Default RAG kinds (`hit_at_k`, `must_contain`, `groundedness`, `correctness`, `latency`) have `removable=false`.
- `evaluators`: named implementations; pack `ensure` links them onto entries.
- `experiments` have `dataset_id` only. `POST .../evaluate-pack` uses the project pack.

## Approach

Keep pack *behavior* as fallback. Replace pack *storage* with versioned sets plus row-level entries. Migrate existing JSONB packs into a project default set named `Default` version 1.

## Data model

### `metrics_sets`

| Column | Notes |
| --- | --- |
| `id` | UUID PK |
| `project_id` | FK `projects.id` ON DELETE CASCADE |
| `name` | trimmed, non-empty; display name |
| `version` | integer ≥ 1 |
| `description` | optional text |
| `is_project_default` | boolean, default false |
| `created_at` | timestamptz |

Constraints:

- Unique `(project_id, name, version)` (same pattern as datasets).
- Unique partial index: at most one row with `is_project_default = true` per `project_id`.
- The project default set cannot be deleted.

### `metrics_set_entries`

| Column | Notes |
| --- | --- |
| `id` | UUID PK |
| `metrics_set_id` | FK `metrics_sets.id` ON DELETE CASCADE |
| `kind` | non-empty; unique per set |
| `enabled` | boolean |
| `threshold` | float, nullable |
| `config` | JSONB, default `{}` |
| `evaluator_id` | FK `evaluators.id` ON DELETE RESTRICT, nullable |
| `is_default` | boolean, default false |
| `created_at` | timestamptz |

Constraints:

- Unique `(metrics_set_id, kind)`.
- Rows with `is_default = true` cannot be deleted. They may be disabled and may have `threshold` / `config` updated.
- `is_default = true` is only set on seed RAG kinds of the project default set (migrated from `removable=false`). Custom sets copy those kinds as normal rows (`is_default = false`) so they remain removable on non-default sets.

### `experiments`

- Add nullable `metrics_set_id` FK `metrics_sets.id` ON DELETE RESTRICT.
- `null` means “use the project default set at score time”.
- The referenced set must belong to the same `project_id`.

### Drop

After data backfill, drop `metrics_packs`.

## Migration (Alembic 0009)

1. Create `metrics_sets` and `metrics_set_entries`.
2. For each `metrics_packs` row:
   - Insert set `name='Default'`, `version=1`, `is_project_default=true`.
   - For each JSONB entry, insert a row with `is_default = not removable` (missing `removable` treated as `true` so the row is deletable).
3. For projects with no pack row, do not insert a set (lazy `ensure` still creates Default v1, same as today’s pack ensure).
4. Drop `metrics_packs`.

Existing experiments keep `metrics_set_id` null and therefore keep falling back to the project default set.

## Versioning and edits

- Creating a set: `version=1`, caller supplies name, optional description, and entries. `POST` cannot set `is_project_default`; only migration and `ensure` create/keep the Default set. Creating other sets never steals the project default flag.
- In-place PATCH of entries is allowed only if no experiment references that `metrics_set_id`.
- If any experiment references the set, in-place mutation returns **409**. The client must `POST .../version` to copy entries into `version+1` (same name) and apply the patch there. `is_project_default` does **not** move to the new version: Default v1 stays the project fallback unless a dedicated “promote default” operation is added later (out of scope). Edits to the unused Default set (no experiments pointing at that UUID) may still PATCH in place, except `is_default` rows cannot be removed.
- `POST .../version` always creates the next integer version for that `(project_id, name)`.

## Scoring

Resolution order for `POST /experiments/{id}/evaluate-pack`:

1. If the request body includes `metrics_set_id`, use that set (must be same project).
2. Else if `experiment.metrics_set_id` is set, use that set.
3. Else use the project set with `is_project_default=true` (ensure/create Default v1 if missing, same as today’s `EnsureMetricsPack`).
4. If none exists after ensure → 404.

Before scoring, enabled entries are linked to evaluators the same way `EnsureMetricsPack` works today: if `evaluator_id` is missing, find-or-create a project evaluator whose name matches `kind` and write the id onto the entry. Then run all enabled entries that have an `evaluator_id`.

Optional body flag `save_as_default: true` with `metrics_set_id` updates `experiment.metrics_set_id` after a successful resolve (before or after the run; persist even if some evaluators fail, as long as the set itself is valid). Default `false`: override applies only to that run.

`POST /experiments/{id}/evaluate` with `evaluator_ids` is unchanged (ad-hoc, ignores sets).

## HTTP API

New:

- `GET /api/v1/projects/{project_id}/metrics-sets` — list (include entry counts / enabled counts).
- `POST /api/v1/projects/{project_id}/metrics-sets` — create v1.
- `GET /api/v1/metrics-sets/{metrics_set_id}` — set + entries.
- `PATCH /api/v1/metrics-sets/{metrics_set_id}` — in-place entry/metadata edits when unreferenced; 409 if referenced.
- `POST /api/v1/metrics-sets/{metrics_set_id}/version` — body: optional description + entry patches; returns the new set.
- `DELETE /api/v1/metrics-sets/{metrics_set_id}` — 409 if `is_project_default` or referenced by experiments.
- `DELETE /api/v1/metrics-sets/{id}/entries/{entry_id}` — 409 if `is_default`.
- `POST /api/v1/projects/{project_id}/experiments` — optional `metrics_set_id`.
- `POST /api/v1/experiments/{id}/evaluate-pack` — optional `metrics_set_id`, optional `save_as_default`.

Alias (map onto the project default set; keep request/response shapes compatible with today’s pack):

- `GET /api/v1/projects/{project_id}/metrics-pack`
- `PUT /api/v1/projects/{project_id}/metrics-pack`
- `POST /api/v1/projects/{project_id}/metrics-pack/ensure`

PUT/ensure on the alias still cannot drop `is_default` kinds (same as required pack kinds today). Alias PUT is in-place on Default and follows the same 409-if-referenced rule.

Error mapping:

- Default set or `is_default` entry delete → 409
- In-place edit of a referenced set → 409
- `metrics_set_id` unknown or other project → 404
- Evaluate with no set and no default after ensure → 404

## Application / domain

- Replace JSONB-centric `MetricsPack` with `MetricsSet` + `MetricsSetEntry`. Keep a thin `MetricsPack` facade used only by alias routes if that reduces churn; otherwise rewrite pack use cases to load the default set.
- Creating a `rag_qa` dataset still ensures the project default set exists (today’s `EnsureMetricsPack` side effect).
- `ScoreExperimentFromPack` loads the resolved set instead of `GetMetricsPack`.

## UI

- `/metrics`: list of sets (name, version, “Default progetto” badge, enabled-entry count). Create, open, duplicate-as-new-version.
- Detail: same entry table as the current pack editor. Hide delete on `is_default` rows. If the set is referenced, show “Crea versione N+1” instead of silent in-place save.
- Create experiment: metrics-set dropdown, project default preselected (stored as `null` or as the default set UUID — store `null` when the user leaves the preselected Default so fallback stays live if Default is later versioned; if the user explicitly picks Default v1, store that UUID). **Decision:** preselected Default is submitted as `null` (fallback). Choosing any specific row, including Default v1 from the list after changing selection, stores that UUID.
- Experiment detail: show bound set or “Project default”. Score uses bound set. Override dialog picks another set for the run; checkbox “Salva come default di questo esperimento” sends `save_as_default`.
- Ad-hoc “Run evaluators” unchanged.

## Testing

- Migration 0009: JSONB → Default v1 rows; `is_default` from `not removable`; skip when no pack.
- Domain: cannot delete default set / `is_default` rows; version bump; unique name+version; at most one project default.
- API: CRUD; alias pack; create experiment with/without `metrics_set_id`; evaluate-pack resolution (body override, experiment default, project fallback); `save_as_default`; 409 paths.
- Frontend coverage aligned with dataset list/detail tests where they exist; otherwise component-level behavior for dropdown and override checkbox.

## Open decisions (resolved)

- Approach: parallel sets + keep pack *behavior* as fallback; storage unified to sets/rows.
- Experiment: default at create + override at score (`save_as_default` optional).
- Versioning: new version on change when the set is already referenced; in-place only if unused.
- `is_default` only on seed rows of the project default set, not on copies in custom sets.
