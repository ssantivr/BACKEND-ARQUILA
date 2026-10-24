# BACKEND-ARQUILA

API de ARQUILA, una aplicación para organizar proyectos de arquitectura. Es una de las tres partes del proyecto:

```text
ARQUILA
├── FRONTEND-ARQUILA        Interfaz (React)
├── BACKEND-ARQUILA         Este repositorio
└── BASE-DE-DATOS-ARQUILA   Migraciones y datos de ejemplo (PostgreSQL)
```

## Tecnología

Python 3.12 y FastAPI, con SQLAlchemy y psycopg sobre PostgreSQL, Argon2 para las contraseñas y pytest para las pruebas. Ruff para el formato y las reglas de estilo.

## Requisitos

- Python 3.12 con `pip`.
- PostgreSQL 16 o superior.
- El repositorio `BASE-DE-DATOS-ARQUILA` clonado junto a este:

  ```text
  carpeta/
  ├── BACKEND-ARQUILA/
  └── BASE-DE-DATOS-ARQUILA/
  ```

## Instalación

En Windows:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
```

En Linux o macOS cambia la activación: `source .venv/bin/activate`.

## Variables de entorno

Copiar `.env.example` a `.env` y completarlo. El archivo `.env` no se sube al repositorio.

En producción (`ENVIRONMENT=production`, o en Vercel) una variable que falta o está vacía toma el valor seguro: `COOKIE_SECURE=1`, `STATE_STORAGE=database` y `FILE_STORAGE=database`. Un valor explícito se respeta, pero si debilita el servidor (`COOKIE_SECURE=0`, `STATE_STORAGE=memory`, `FILE_STORAGE=disk` en Vercel, o `JWT_SECRET` ausente o corta) se registra al arrancar el evento `insecure_setting` con el nombre de la variable, nunca su valor. Nada de esto impide arrancar.

| Variable | Uso | Por defecto |
|---|---|---|
| `DATABASE_URL` | Conexión a PostgreSQL. Obligatoria. | — |
| `DATABASE_DIR` | Carpeta de `BASE-DE-DATOS-ARQUILA`. | `../BASE-DE-DATOS-ARQUILA` |
| `API_HOST` | Dirección en la que escucha la API. | `127.0.0.1` |
| `API_PORT` | Puerto de la API. | `8000` |
| `UPLOAD_DIR` | Carpeta de los archivos subidos. | `uploads` |
| `STATE_STORAGE` | `memory` guarda en memoria el historial de «Deshacer» y los límites de intentos; `database` los guarda en PostgreSQL. | `memory`; en producción, `database` |
| `REGISTRATION_LIMIT_PER_HOUR` | Registros que admite cada dirección IP por hora, logren o no crear la cuenta. Un valor que no sea un entero mayor que 0 vuelve al de por defecto. Se lee al arrancar. | `10` |
| `FILE_STORAGE` | `disk` guarda los archivos en `UPLOAD_DIR`; `database` los guarda en PostgreSQL. | `disk`; en producción, `database` |
| `COOKIE_SECURE` | `1` envía la cookie de sesión solo por HTTPS y añade `Strict-Transport-Security`. | `0`; en producción, `1` |
| `COOKIE_SAMESITE` | `lax`, `strict` o `none`. Usar `none` solo si la interfaz está en otro sitio; obliga a HTTPS. | `lax` |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING` o `ERROR`. | `INFO` |
| `APP_URL` | Dirección de la interfaz; se usa en el enlace de recuperación de contraseña y como origen permitido. | `http://localhost:5173` |
| `CORS_ORIGINS` | Orígenes permitidos, separados por comas. | `APP_URL` |
| `OLLAMA_URL`, `OLLAMA_MODEL` | Modelo local del asistente. | `http://127.0.0.1:11434`, primer modelo instalado |
| `JWT_SECRET` | Clave de al menos 32 bytes para los tokens de `/api/v1/auth/token`. Sin ella esa ruta responde 503; el resto funciona. | — |
| `ENVIRONMENT` | `production` activa las comprobaciones y los valores por defecto de producción. En Vercel siempre están activos. | — |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Correo de recuperación de contraseña. Sin `SMTP_HOST`, el mensaje se muestra en la terminal; en producción, la recuperación responde 503. | — |

## Conexión con la base de datos

1. Crear una base vacía:

   ```bash
   psql -U postgres -c "CREATE DATABASE arquila;"
   ```

2. Poner la conexión en `DATABASE_URL`, por ejemplo `postgresql+psycopg://postgres:CLAVE@localhost:5432/arquila`.

3. Crear las tablas con las migraciones de `BASE-DE-DATOS-ARQUILA`:

   ```bash
   python -m app.migrate          # solo el esquema
   python -m app.migrate --seed   # esquema y datos de ejemplo
   ```

Las migraciones (SQL) viven en `BASE-DE-DATOS-ARQUILA`; los modelos de SQLAlchemy que usa el código están en `app/models.py`.

## Iniciar el servidor

```bash
python -m app.dev
```

Lee `.env`, aplica las migraciones pendientes y arranca la API en `http://127.0.0.1:8000`.

- `http://localhost:8000/docs`: documentación interactiva con todas las operaciones.
- `http://localhost:8000/health`: responde `{"status": "ok"}`.

## Despliegue

`python -m app.dev` está pensado para desarrollo y solo escucha en el propio equipo. En un servidor:

- Poner `API_HOST=0.0.0.0` para aceptar conexiones de fuera, detrás de un servidor que dé HTTPS.
- Poner `ENVIRONMENT=production`: así `COOKIE_SECURE` vale `1`, `STATE_STORAGE` vale `database` y `FILE_STORAGE` vale `database` si no se definen. Poner la dirección pública de la interfaz en `APP_URL`.
- Para guardar los archivos en disco, definir `FILE_STORAGE=disk` y apuntar `UPLOAD_DIR` a una carpeta que se conserve entre despliegues.
- No poner `STATE_STORAGE=memory` en producción. Con `memory` (el valor por defecto en desarrollo), los límites de intentos de inicio de sesión y de cambio de contraseña y el historial de «Deshacer» viven en la memoria de cada proceso: se pierden al reiniciar y no se comparten entre instancias, así que el límite de intentos se puede esquivar repartiendo las peticiones.

### En Vercel

La API está publicada en <https://arquila-backend.vercel.app> y la interfaz en <https://arquila-frontend.vercel.app>.

- Vercel detecta FastAPI a partir de `app/main.py` y `requirements.txt`; no hace falta configuración.
- La base es un PostgreSQL de Neon creado desde el Marketplace de Vercel, que deja `DATABASE_URL` en el proyecto. El backend acepta la forma `postgresql://` que entrega Neon.
- Variables del proyecto: `APP_URL` con la dirección de la interfaz. `COOKIE_SECURE`, `FILE_STORAGE` y `STATE_STORAGE` ya valen `1`, `database` y `database` en Vercel sin definirlas, porque ni el disco ni la memoria se conservan entre peticiones; si se definen con otro valor, se respetan y se registra `insecure_setting`.
- `STATE_STORAGE=database` y `FILE_STORAGE=database` necesitan las tablas `runtime_state` y `file_contents` (migraciones 011 y 010). Sin ellas el registro, el inicio de sesión y la subida de archivos responden 500, mientras `/health` sigue respondiendo bien.
- Las migraciones no se aplican solas. Se ejecutan desde un equipo con `python -m app.migrate`, poniendo en `DATABASE_URL` la dirección de la base de Vercel.

Limitaciones de este despliegue: Vercel no acepta peticiones de más de 4,5 MB, así que ese es el tamaño máximo de un archivo subido, aunque el backend admita 20 MB; y el asistente responde con las reglas fijas, porque no hay un Ollama al que conectarse.

## Endpoints principales

La sesión viaja en una cookie `HttpOnly`. Las rutas con datos de proyectos requieren sesión iniciada.

| Recurso | Rutas |
|---|---|
| Estado | `GET /health` |
| Autenticación | `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET`, `PATCH /auth/me`, `POST /auth/change-password`, `POST /auth/password-reset`, `POST /auth/password-reset/confirm` |
| Proyectos | `GET`, `POST /projects` · `GET`, `PATCH`, `DELETE /projects/{id}` · `POST /projects/{id}/duplicate`, `/archive`, `/unarchive` |
| Tareas | `GET`, `POST /projects/{id}/tasks` · `GET`, `PATCH`, `DELETE /tasks/{id}` |
| Versiones | `GET`, `POST /projects/{id}/versions` · `GET /versions/{id}` · `POST /versions/{id}/restore` |
| Historial | `GET /projects/{id}/activity` |
| Escena | `GET`, `PUT /projects/{id}/scene-settings` · `GET`, `POST /projects/{id}/walkthrough-points` · `GET`, `PATCH`, `DELETE /walkthrough-points/{id}` |
| Preferencias y notificaciones | `GET`, `PUT /users/me/preferences` · `GET /notifications` · `POST /notifications/{id}/read`, `/notifications/read-all` |
| Plantillas | `GET /templates` · `POST /templates/{template_id}/projects` |
| Terrenos, materiales, planos, elevaciones, cuartos, componentes | `GET`, `POST /projects/{id}/{recurso}` · `GET`, `PATCH`, `DELETE /{recurso}/{id}`, con `terrains`, `materials`, `plans`, `elevations`, `rooms` y `components` |
| Archivos | `GET`, `POST /projects/{id}/files` · `GET`, `DELETE /files/{id}` · `GET /files/{id}/content` |
| Estructura | `GET /projects/{id}/structure` · `PATCH /projects/{id}/structure/roof` · `PATCH /projects/{id}/structure/{kind}/{element_id}/surface` |
| Recomendaciones | `GET`, `POST /projects/{id}/recommendations` · `POST /projects/{id}/recommendations/generate` · `DELETE /recommendations/{id}` |
| Deshacer | `GET`, `POST /projects/{id}/undo` · `POST /projects/{id}/redo` |
| Asistente | `GET /assistant/status` · `GET`, `POST /projects/{id}/conversations` · `GET`, `DELETE /conversations/{id}` · `POST /conversations/{id}/messages` |
| Resumen | `GET /summary` |

## Servicios externos

No se usa ninguna API externa de pago ni con clave.

- **Ollama** (opcional): modelo de IA local, sin clave. Si no está en marcha, el asistente responde con reglas fijas.
- **SMTP** (opcional): correo de recuperación de contraseña.

`python -m app.check` comprueba el asistente, y `python -m app.check correo@ejemplo.com` también el correo.

## Conexión con la interfaz

`FRONTEND-ARQUILA` llama a esta API. Solo se aceptan peticiones de navegador desde los orígenes de `APP_URL` o `CORS_ORIGINS`. Si la interfaz se sirve desde otro sitio (otro dominio registrado), hay que definir además `COOKIE_SAMESITE=none` y usar HTTPS, o el navegador no enviará la cookie de sesión.

## Organización

```text
app/
├── api/               Rutas
├── services/          Reglas de la aplicación
├── repositories/      Acceso a la base de datos
├── data_structures/   Estructuras de datos implementadas a mano
├── models.py          Modelos de SQLAlchemy
├── schemas.py         Validación de entrada y salida
└── main.py            Aplicación, CORS y manejo de errores
tests/                 Pruebas
```

## Pruebas y calidad

```bash
pytest
ruff format --check app tests
ruff check app tests
```

`pytest` usa SQLite en memoria. Para ejecutarlo contra PostgreSQL, definir `TEST_DATABASE_URL` con una base cuyo nombre termine en `test` (se vacía antes de cada prueba).

## Documentación

- `docs/BACKEND_Y_API.md`: decisiones del backend (autenticación, seguridad, registro de eventos, archivos, IA).
- `docs/API_CONTRATO.md`: contrato de las rutas añadidas en octubre de 2026 (cuerpos, respuestas, errores y ejemplos), para la interfaz.
- `docs/PENDIENTE.md`: lo que el backend no hace todavía (renderizado fotorrealista, análisis estructural, exportación a PDF) y lo que haría falta.
- La documentación general del proyecto (requerimientos, estructuras de datos, complejidad, pruebas) está en el repositorio [ARQUILA](https://github.com/ssantivr/ARQUILA).

Para que Ruff formatee los archivos antes de cada commit, activar los hooks una vez con `pre-commit install`.
