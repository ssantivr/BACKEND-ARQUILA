# Contrato de la API: rutas nuevas

Este documento describe, para la interfaz, las rutas y los campos que se añadieron en octubre de 2026. Las rutas anteriores no cambian: solo ganan campos opcionales, que se indican aquí. La lista completa y siempre actualizada está en `/docs` (OpenAPI) del servidor en marcha.

## Convenciones comunes

- **Sesión**: todas las rutas de este documento exigen la cookie `arquila_session` (la que dejan `POST /auth/register` y `POST /auth/login`). Desde el navegador hay que enviar las peticiones con `credentials: "include"`.
- **Propiedad**: todo lo que cuelga de un proyecto solo es visible para su dueño. Un recurso de otro usuario responde **404**, igual que uno inexistente, para no revelar qué identificadores existen.
- **Fechas**: ISO 8601 (`2026-10-20T22:22:53`, o `2026-11-30` para fechas sin hora).
- **Errores**: siempre JSON con `detail`.
  - Errores de negocio: `{"detail": "Texto en inglés"}`. Son los mismos mensajes fijos de siempre en estas rutas, para que la interfaz los traduzca en `src/utils/errors.ts`. Los nuevos están en la tabla de abajo.
  - Datos inválidos (422 de validación): el formato estándar de FastAPI, `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}`.

| Código | Cuándo |
|---|---|
| 401 | Sin sesión o sesión caducada: `{"detail": "Not authenticated"}`. |
| 404 | El recurso no existe o es de otro usuario. |
| 409 | Conflicto con datos existentes (nombre de proyecto repetido). |
| 413 / 415 | Archivo demasiado grande / de un tipo no admitido (ver «Archivos»). |
| 422 | Datos inválidos, por validación o por una regla de negocio. |
| 429 | Demasiados intentos fallidos. |

Mensajes nuevos que la interfaz debería traducir:

| `detail` | Ruta |
|---|---|
| `Version not found` | `/versions/{id}` |
| `Task not found` | `/tasks/{id}` |
| `Notification not found` | `/notifications/{id}/read` |
| `Walkthrough point not found` | `/walkthrough-points/{id}` |
| `File not found` | `PATCH /auth/me` |
| `File not found in this project` | `PATCH /projects/{id}` (portada) |
| `The cover must be a PNG, JPEG or WebP image` | `PATCH /projects/{id}` |
| `The avatar must be a PNG, JPEG or WebP image` | `PATCH /auth/me` |
| `A task that is done must have a progress of 100` | tareas |
| `A task can only be assigned to the owner of the project` | tareas |
| `The current password is incorrect` | `POST /auth/change-password` |
| `The new password must be different from the current one` | `POST /auth/change-password` |
| `Too many failed attempts, try again later` | `POST /auth/change-password` (429) |

## Proyectos

### Campos nuevos en `ProjectRead`

Todas las respuestas que devuelven un proyecto (`GET /projects`, `GET/PATCH /projects/{id}`, etc.) llevan además:

| Campo | Tipo | Significado |
|---|---|---|
| `progress` | entero 0–100 | Avance del proyecto. Por defecto `0`. |
| `archived_at` | fecha o `null` | Cuándo se archivó. `null` si no está archivado. |
| `cover_file_id` | entero o `null` | Archivo de imagen usado como portada. Se descarga con `GET /files/{id}/content`. |

### `GET /projects` — listar, buscar, filtrar, ordenar y paginar

Sin `page` ni `page_size` la respuesta es **la lista de siempre** (un array de `ProjectRead`). Con cualquiera de los dos, la respuesta pasa a ser una página. Los filtros funcionan en los dos modos.

| Parámetro | Tipo | Por defecto | Uso |
|---|---|---|---|
| `page` | entero ≥ 1 | — | Número de página. Activa la respuesta paginada. Si solo se envía `page_size`, vale `1`. |
| `page_size` | entero 1–100 | `20` | Tamaño de página. Activa la respuesta paginada. |
| `q` | texto ≤ 160 | — | Busca en nombre, descripción y ubicación, sin distinguir mayúsculas. |
| `search` | texto | — | Como antes: busca solo en el nombre. |
| `status` | `draft`, `active`, `archived` | — | Estado del proyecto. |
| `type` | `house`, `apartment_building`, `commercial`, `mixed_use` | — | Proyectos que tienen al menos una propiedad (`/api/v1/properties`) de ese tipo. |
| `archived` | `true` / `false` | — | Solo archivados / solo no archivados. Sin el parámetro salen todos, como antes. |
| `sort` | `id`, `name`, `created_at`, `updated_at`, `status`, `progress` | `id` | Campo de orden. `name` no distingue mayúsculas. |
| `order` | `asc`, `desc` | `asc` | Sentido. Los empates se deshacen por `id` en el mismo sentido. |

La cabecera `X-Total-Count` lleva siempre el total de resultados con los filtros aplicados (el navegador puede leerla: CORS la expone).

Respuesta paginada (200):

```json
{
  "items": [{"id": 3, "name": "Casa del lago", "status": "active", "progress": 80, "archived_at": null, "cover_file_id": 12, "...": "..."}],
  "total": 14,
  "page": 2,
  "page_size": 5
}
```

Errores: 401; 422 si un parámetro no es válido (`page=0`, `page_size=101`, `sort=owner_id`, `type=castle`...).

Ejemplo: `GET /projects?q=casa&archived=false&sort=updated_at&order=desc&page=1&page_size=12`

### `PATCH /projects/{id}` — campos nuevos

| Campo | Tipo | Regla |
|---|---|---|
| `progress` | entero 0–100 | `null` se ignora. |
| `cover_file_id` | entero o `null` | Debe ser un archivo **del mismo proyecto** y una imagen PNG, JPEG o WebP. `null` quita la portada. |

Cambiar `status` a `archived` rellena `archived_at`; cambiarlo a otro valor lo vacía. Si se elimina el archivo de la portada, `cover_file_id` vuelve a `null`.

Errores: 404 `File not found in this project` (archivo inexistente, de otro proyecto o de otro usuario); 422 `The cover must be a PNG, JPEG or WebP image`; 422 si `progress` está fuera de rango.

```http
PATCH /projects/7
{"progress": 45, "cover_file_id": 12}
```

### `POST /projects/{id}/archive` y `POST /projects/{id}/unarchive`

Sin cuerpo. Responden 200 con el `ProjectRead`.

- `archive` pone `status: "archived"` y la fecha `archived_at`. Si ya estaba archivado no cambia nada (la fecha se conserva).
- `unarchive` vacía `archived_at` y devuelve al proyecto el estado que tenía antes de archivarlo (`draft` o `active`). Si no se conoce, por ejemplo porque se archivó con `PATCH`, queda `active`. Si no estaba archivado no cambia nada.

Errores: 401, 404.

### `POST /projects/{id}/duplicate`

Cuerpo opcional: `{"name": "Variante B"}` (1–160 caracteres).

Crea un proyecto nuevo del mismo usuario con una copia de: terrenos y sus vértices, materiales, elevaciones, planos con sus cuartos y componentes, tareas, puntos de recorrido y ajustes de escena. También copia descripción, ubicación, cubierta y avance.

No copia: archivos (los planos y elevaciones copiados quedan sin archivo y el proyecto sin portada), recomendaciones, conversaciones del asistente, versiones, historial, ni los datos de `/api/v1` (propiedades, unidades, elementos espaciales, pasos de recorrido, registro de obras).

- Sin nombre, se llama `«nombre» (copia)`, y si ya existe, `«nombre» (copia) (2)`, `(3)`...
- El estado se copia, salvo `archived`, que pasa a `draft`.

Respuesta: **201** con el `ProjectRead` del proyecto nuevo.

Errores: 401; 404; 409 si el nombre enviado ya existe; 422 si el nombre está vacío o es demasiado largo.

## Tareas

`TaskRead`:

```json
{
  "id": 4,
  "project_id": 7,
  "title": "Pedir permisos",
  "description": "Municipio",
  "status": "in_progress",
  "assignee_id": 1,
  "due_date": "2026-11-30",
  "progress": 40,
  "created_by": 1,
  "created_at": "2026-10-20T15:02:11",
  "updated_at": "2026-10-20T15:10:40"
}
```

| Método y ruta | Cuerpo | Respuesta |
|---|---|---|
| `GET /projects/{id}/tasks?status=` | — | 200, lista ordenada por `id`. `status` opcional: `todo`, `in_progress`, `done`. |
| `POST /projects/{id}/tasks` | `TaskCreate` | 201, `TaskRead` |
| `GET /tasks/{id}` | — | 200, `TaskRead` |
| `PATCH /tasks/{id}` | `TaskUpdate` | 200, `TaskRead` |
| `DELETE /tasks/{id}` | — | 204 |

`TaskCreate`: `title` (obligatorio, 1–160), `description` (≤ 2000), `status` (`todo` por defecto), `assignee_id`, `due_date` (`AAAA-MM-DD`), `progress` (0–100).
`TaskUpdate`: los mismos campos, todos opcionales. `description`, `assignee_id` y `due_date` se pueden vaciar con `null`; en los demás, `null` se ignora.

Reglas:

- Una tarea `done` tiene `progress: 100`. Al crearla o pasarla a `done` sin enviar `progress`, se rellena solo. Enviar `done` con otro avance responde 422 `A task that is done must have a progress of 100`.
- Los proyectos no se comparten, así que `assignee_id` solo puede ser el propio usuario o `null`; otro valor responde 422 `A task can only be assigned to the owner of the project`.

Errores: 401; 404 (`Project not found`, `Task not found`); 422.

## Versiones

Una versión es una copia del contenido del proyecto en un momento dado (la misma lista de contenidos que copia «Duplicar», más descripción, ubicación, cubierta, avance y portada). Los archivos no se copian: la versión solo guarda a qué archivo apuntaba cada plano, elevación o portada.

`VersionRead`:

```json
{
  "id": 9,
  "project_id": 7,
  "version_number": 3,
  "label": "Anteproyecto",
  "created_by": 1,
  "created_at": "2026-10-20T16:00:00",
  "contents": {"terrains": 1, "plans": 2, "rooms": 6, "components": 8, "materials": 5, "elevations": 2, "tasks": 3, "walkthrough_points": 4}
}
```

| Método y ruta | Cuerpo | Respuesta |
|---|---|---|
| `GET /projects/{id}/versions` | — | 200, lista de `VersionRead`, la más reciente primero. |
| `POST /projects/{id}/versions` | opcional: `{"label": "Anteproyecto"}` (1–160) | 201, `VersionRead`. Los números son correlativos por proyecto (1, 2, 3...). |
| `GET /versions/{id}` | — | 200, `VersionRead` + `snapshot` (el contenido completo en JSON). |
| `POST /versions/{id}/restore` | — | 200, `ProjectRead` del proyecto restaurado. |

Restaurar:

1. Guarda primero el estado actual como una versión nueva con la etiqueta `Before restoring version N`, para que la restauración se pueda deshacer restaurando esa versión.
2. Sustituye el contenido del proyecto por el de la versión. El nombre, el estado y el archivado no cambian.
3. Las referencias a archivos que ya no existen o no son del proyecto quedan en `null`. Los elementos espaciales, pasos de recorrido y obras de `/api/v1` que apuntaban a cuartos sustituidos se conservan sin cuarto (`room_id: null`).
4. Vacía el historial de «Deshacer» del proyecto, porque sus entradas pertenecen al estado anterior.

Errores: 401; 404 (`Project not found`, `Version not found`); 422 si la etiqueta no es válida.

## Historial de actividad

### `GET /projects/{id}/activity`

| Parámetro | Tipo | Por defecto |
|---|---|---|
| `page` | entero ≥ 1 | `1` |
| `page_size` | entero 1–100 | `50` |
| `entity_type` | texto ≤ 40 | — (todas) |

Respuesta 200, la más reciente primero:

```json
{
  "items": [
    {
      "id": 31,
      "project_id": 7,
      "user_id": 1,
      "action": "updated",
      "entity_type": "terrain",
      "entity_id": 5,
      "detail": {"label": "Lote 14", "fields": ["area_m2", "soil_type"]},
      "created_at": "2026-10-20T16:05:12"
    }
  ],
  "total": 31,
  "page": 1,
  "page_size": 50
}
```

Se registra automáticamente:

| `action` | `entity_type` | `detail` |
|---|---|---|
| `created`, `updated`, `deleted` | `project`, `terrain`, `material`, `plan`, `elevation`, `room`, `component`, `file`, `recommendation`, `task`, `walkthrough_point` | `label` (nombre o título); en `updated`, `fields` con los campos enviados. |
| `updated` | `scene_settings` | `label: "Scene"`, `fields`. |
| `restored` | el tipo restaurado | Restauración desde «Deshacer». Rehacer registra `deleted`. |
| `archived`, `unarchived` | `project` | En `archived`, `previous_status`. |
| `duplicated` | `project` | En el proyecto nuevo, con `source_project_id`. |
| `version_saved`, `version_restored` | `version` | `version_number`; en `version_restored`, `backup_version_id`. |

No se registran las recomendaciones generadas automáticamente ni los cambios hechos por `/api/v1`. Al eliminar un proyecto se borra su historial.

Errores: 401; 404; 422 si un parámetro no es válido.

## Perfil y contraseña

### Campos nuevos en `UserRead`

`POST /auth/register`, `POST /auth/login`, `GET /auth/me` y `PATCH /auth/me` devuelven además `display_name` (texto o `null`) y `avatar_file_id` (entero o `null`).

### `PATCH /auth/me`

```json
{"display_name": "Arq. Ana Pérez", "avatar_file_id": 12}
```

- `display_name`: hasta 120 caracteres. Se quitan los espacios de los extremos; un texto vacío o `null` lo borra.
- `avatar_file_id`: una imagen PNG, JPEG o WebP subida a cualquiera de los proyectos del usuario (con `POST /projects/{id}/files`). `null` lo quita. Si se elimina el archivo, el avatar vuelve a `null`.
- Los campos que no se envían no cambian.

Respuesta: 200 con el `UserRead`.
Errores: 401; 404 `File not found`; 422 `The avatar must be a PNG, JPEG or WebP image`; 422 de validación.

### `POST /auth/change-password`

```json
{"current_password": "la-actual", "new_password": "una-nueva-de-8-o-mas"}
```

- Comprueba la contraseña actual, guarda la nueva con Argon2id y **cierra todas las demás sesiones** del usuario; la sesión que hace la petición sigue abierta. Los tokens de `/api/v1/auth/token` emitidos antes dejan de valer.
- Deja una notificación «Contraseña cambiada».
- Tras 5 contraseñas actuales incorrectas en 15 minutos responde 429. Con `STATE_STORAGE=database` la cuenta se guarda en la base y vale para todas las instancias.

Respuesta: **204** sin cuerpo.
Errores: 401 (sin sesión); 422 `The current password is incorrect` (no es 401, para que la interfaz no lo confunda con una sesión caducada); 422 `The new password must be different from the current one`; 422 si la nueva tiene menos de 8 o más de 128 caracteres; 429.

## Preferencias

### `GET /users/me/preferences` y `PUT /users/me/preferences`

```json
{
  "theme": "dark",
  "units": "metric",
  "density": "comfortable",
  "reduce_motion": false,
  "preview_quality": "medium",
  "camera_defaults": {"fov": 60, "height_m": 1.6},
  "notifications": {"tasks": true}
}
```

| Campo | Valores | Por defecto |
|---|---|---|
| `theme` | `light`, `dark`, `auto` | `auto` |
| `units` | `metric`, `imperial` | `metric` |
| `density` | `compact`, `comfortable`, `spacious` | `comfortable` |
| `reduce_motion` | booleano | `false` |
| `preview_quality` | `low`, `medium`, `high` | `medium` |
| `camera_defaults` | objeto libre, claves de 1–40 caracteres, ≤ 4000 caracteres en JSON | `{}` |
| `notifications` | objeto `{clave: booleano}`, hasta 30 claves | `{}` |

- `GET` responde los valores por defecto mientras el usuario no haya guardado nada.
- `PUT` cambia los campos que recibe y conserva los demás; responde 200 con todas las preferencias.

Errores: 401; 422.

## Notificaciones

`NotificationRead`: `{"id": 3, "title": "Contraseña cambiada", "body": "...", "read_at": null, "created_at": "..."}`. El título y el cuerpo ya vienen en español y se muestran tal cual.

| Método y ruta | Respuesta |
|---|---|
| `GET /notifications?unread=false&limit=50` | 200, lista, la más reciente primero. `unread=true` deja solo las no leídas; `limit` 1–200. |
| `POST /notifications/{id}/read` | 200, `NotificationRead` con `read_at`. Si ya estaba leída, conserva la fecha. |
| `POST /notifications/read-all` | 200, `{"updated": 2}`: cuántas se marcaron. |

Hoy solo se genera la notificación del cambio de contraseña (ver `PENDIENTE.md`).

Errores: 401; 404 `Notification not found`; 422.

## Escena

### `GET /projects/{id}/scene-settings` y `PUT /projects/{id}/scene-settings`

```json
{
  "project_id": 7,
  "lighting": {"preset": "sunset", "intensity": 0.8, "shadows": true},
  "camera_presets": [
    {"name": "Entrada", "position": [1, 1.6, 8], "target": [5, 1.2, 0], "fov": 55}
  ],
  "updated_at": "2026-10-20T16:30:00"
}
```

- `lighting`: objeto plano de hasta 30 claves (1–40 caracteres); cada valor es número, booleano o texto de hasta 200 caracteres. El backend lo guarda tal cual; su significado lo decide la interfaz.
- `camera_presets`: hasta 20 cámaras guardadas. `name` 1–80; `position` y `target` son `[x, y, z]` en metros, cada valor entre −100 000 y 100 000; `fov` opcional, entre 10 y 120 grados.
- `GET` responde `lighting: {}`, `camera_presets: []` y `updated_at: null` mientras no se haya guardado nada.
- `PUT` cambia los campos que recibe (cada uno se reemplaza entero) y conserva el otro.

Errores: 401; 404; 422.

### Puntos de recorrido

`WalkthroughPointRead`: `{"id": 2, "project_id": 7, "name": "Sala", "position": [2, 1.6, 3], "target": [4, 1.5, 3], "sort_order": 1, "created_at": "...", "updated_at": "..."}`

| Método y ruta | Cuerpo | Respuesta |
|---|---|---|
| `GET /projects/{id}/walkthrough-points` | — | 200, lista por `sort_order` y luego `id`. |
| `POST /projects/{id}/walkthrough-points` | `name` (1–160), `position`, `target`, `sort_order` (0–100 000, por defecto 0) | 201 |
| `GET /walkthrough-points/{id}` | — | 200 |
| `PATCH /walkthrough-points/{id}` | los mismos campos, opcionales | 200 |
| `DELETE /walkthrough-points/{id}` | — | 204 |

Son independientes de los pasos de `/api/v1/interior-walkthrough`, que siguen igual.

Errores: 401; 404 (`Project not found`, `Walkthrough point not found`); 422.

## Resumen

### `GET /summary` — campos nuevos

| Campo | Cálculo |
|---|---|
| `in_progress_projects` | Proyectos `active`, no archivados, con avance menor que 100. |
| `completed_projects` | Proyectos con avance 100, archivados o no. |
| `materials` | Número de materiales en todos los proyectos del usuario. |
| `plans` | Número de planos en todos los proyectos del usuario. |

Siguen `projects` (total), `draft_projects`, `active_projects`, `archived_projects`, `terrains`, `total_area_m2` y `materials_total_cost`. Todo sale de la base de datos y solo cuenta datos del usuario.

## Archivos

Sin cambios de contrato. Recordatorio: el tipo se detecta por el contenido (PDF, PNG, JPEG, WebP), no por la extensión; más de 20 MB responde 413 `File exceeds the 20 MB limit` y otro tipo 415 `Only PDF, PNG, JPEG and WebP files are supported`. En Vercel el límite real es 4,5 MB por petición, que impone la plataforma antes de llegar al backend. Portadas y avatares solo admiten imágenes.

## CORS y cabeceras

- Se admiten `GET`, `POST`, `PUT`, `PATCH` y `DELETE` desde los orígenes de `APP_URL` o `CORS_ORIGINS`, con credenciales.
- Se expone `X-Total-Count`.
- Todas las respuestas llevan `Permissions-Policy: camera=(), microphone=(), geolocation=()` además de las cabeceras de siempre; con `COOKIE_SECURE=1`, también `Strict-Transport-Security`.
