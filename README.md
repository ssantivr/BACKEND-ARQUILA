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

| Variable | Uso | Por defecto |
|---|---|---|
| `DATABASE_URL` | Conexión a PostgreSQL. Obligatoria. | — |
| `DATABASE_DIR` | Carpeta de `BASE-DE-DATOS-ARQUILA`. | `../BASE-DE-DATOS-ARQUILA` |
| `API_HOST` | Dirección en la que escucha la API. | `127.0.0.1` |
| `API_PORT` | Puerto de la API. | `8010` |
| `UPLOAD_DIR` | Carpeta de los archivos subidos. | `uploads` |
| `STATE_STORAGE` | `memory` guarda en memoria el historial de «Deshacer» y los límites de intentos; `database` los guarda en PostgreSQL. | `memory` |
| `FILE_STORAGE` | `disk` guarda los archivos en `UPLOAD_DIR`; `database` los guarda en PostgreSQL. | `disk` |
| `COOKIE_SECURE` | `1` para enviar la cookie de sesión solo por HTTPS. | `0` |
| `COOKIE_SAMESITE` | `lax`, `strict` o `none`. Usar `none` solo si la interfaz está en otro sitio; obliga a HTTPS. | `lax` |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING` o `ERROR`. | `INFO` |
| `APP_URL` | Dirección de la interfaz; se usa en el enlace de recuperación de contraseña y como origen permitido. | `http://localhost:5173` |
| `CORS_ORIGINS` | Orígenes permitidos, separados por comas. | `APP_URL` |
| `OLLAMA_URL`, `OLLAMA_MODEL` | Modelo local del asistente. | `http://127.0.0.1:11434`, primer modelo instalado |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Correo de recuperación de contraseña. Sin `SMTP_HOST`, el mensaje se muestra en la terminal. | — |

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

## Desarrollo local en Windows

```powershell
Copy-Item .env.example .env
```

Edita `DATABASE_URL` en `.env` para apuntar a tu PostgreSQL local. Crea la base una sola vez:

```powershell
psql -U postgres -c "CREATE DATABASE arquila;"
```

Inicia la API desde `BACKEND-ARQUILA`:

```powershell
.\.venv\Scripts\python.exe -m app.dev
```

`app.dev` carga `.env`, aplica las migraciones pendientes y escucha solo en el equipo local:
`http://127.0.0.1:8010`. La misma API responde en `http://localhost:8010`.

Si prefieres ejecutar Uvicorn directamente, aplica primero las migraciones con
`python -m app.migrate` y exporta `DATABASE_URL` en esa misma terminal:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://postgres:<clave-local>@localhost:5432/arquila"
python -m app.migrate
uvicorn app.main:app --host 127.0.0.1 --port 8010
```

- `http://localhost:8010/docs`: documentación interactiva.
- `http://localhost:8010/health`: comprueba que la API y PostgreSQL responden.

La lectura paramétrica desde texto funciona sin proveedor de IA. Para leer documentos sin enviar
datos fuera del equipo, instala Ollama con un modelo de visión local y configura
`AI_EXTRACTION_PROVIDER=ollama`, `OLLAMA_VISION_MODEL` y `OLLAMA_URL` en `.env`. Gemini y correo
SMTP son opcionales; la aplicación no depende de ellos para iniciar ni para crear proyectos a
partir de una descripción.

## Despliegue

`python -m app.dev` está pensado para desarrollo y solo escucha en el propio equipo. En un servidor:

- Poner `API_HOST=0.0.0.0` para aceptar conexiones de fuera, detrás de un servidor que dé HTTPS.
- Definir `COOKIE_SECURE=1` y poner la dirección pública de la interfaz en `APP_URL`.
- Apuntar `UPLOAD_DIR` a una carpeta que se conserve entre despliegues, o poner `FILE_STORAGE=database` si no hay ninguna.
- Ejecutar una sola instancia, o poner `STATE_STORAGE=database`: sin esa variable, los límites de intentos de inicio de sesión y el historial de «Deshacer» viven en memoria.

### En Render

`render.yaml` crea la API y una base PostgreSQL gratuita desde **New → Blueprint**. Al crear el Blueprint, Render pide `APP_URL`: la dirección de la interfaz, por ejemplo `https://arquila-app.vercel.app`.

- La compilación instala `requirements.txt` y descarga `BASE-DE-DATOS-ARQUILA` en la carpeta `database` (`DATABASE_DIR=database`).
- Al arrancar se ejecuta `python -m app.migrate`, que aplica las migraciones pendientes sin crear cuentas de prueba ni datos de demostración, y luego `uvicorn`.
- Las cuentas de prueba y los 50 proyectos de ejemplo son solo locales; el script `seed_demo_50.sh` rechaza bases remotas.
- `/health` comprueba la base de datos; Render lo usa para saber si el servicio está sano.
- En el plan gratuito el servicio se duerme tras unos minutos sin tráfico (la primera petición tarda unos 50 segundos) y la base caduca a los 30 días.
- La interfaz de Vercel reenvía `/api` al servicio `arquila-backend-juan.onrender.com` desde su `vercel.json`, así que comparten dominio y no hace falta CORS.

### En Vercel

El frontend se publica en `https://arquila-app.vercel.app` desde `FRONTEND-ARQUILA`. El backend permanece en Render; no se despliega FastAPI en Vercel.

- Configura la raíz del proyecto Vercel como `FRONTEND-ARQUILA` y usa `npm run build`.
- El `vercel.json` del frontend reenvía `/api` al servicio de Render.
- Al crear el Blueprint, configura `APP_URL` con el dominio asignado por Vercel.
- No cargues cuentas ni proyectos de prueba en una base de producción. Para probarlos, usa una base local marcada expresamente como `local` y sigue `docs/DEMO_DATA.md` del repositorio de base de datos.

Limitaciones de este despliegue: Vercel no acepta peticiones de más de 4,5 MB, así que ese es el tamaño máximo de un archivo subido, aunque el backend admita 20 MB; y el asistente responde con las reglas fijas, porque no hay un Ollama al que conectarse.

## Endpoints principales

La sesión viaja en una cookie `HttpOnly`. Las rutas con datos de proyectos requieren sesión iniciada.

| Recurso | Rutas |
|---|---|
| Estado | `GET /health` |
| Autenticación | `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`, `POST /auth/password-reset`, `POST /auth/password-reset/confirm` |
| Proyectos | `GET`, `POST /projects` · `GET`, `PATCH`, `DELETE /projects/{id}` |
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
- La documentación general del proyecto (requerimientos, estructuras de datos, complejidad, pruebas) está en el repositorio [ARQUILA](https://github.com/ssantivr/ARQUILA).

Para que Ruff formatee los archivos antes de cada commit, activar los hooks una vez con `pre-commit install`.
