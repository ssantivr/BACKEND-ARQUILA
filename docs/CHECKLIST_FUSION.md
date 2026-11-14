# Comprobaciones antes de fusionar `santiago` en `main`

Para los tres repositorios. Marcar cada punto al comprobarlo; si uno falla, no fusionar.

## 0. Configuración manual antes de fusionar

Nada de esto lo puede hacer el código. Sin estos puntos, la fusión deja caída la API o bloqueada la demo.

### Vercel, proyecto `arquila-backend`, en Production y en Preview

Vercel define `VERCEL=1` en los dos entornos, así que las previews también se detienen si una variable es insegura.

- [ ] `JWT_SECRET`: valor propio de al menos 32 bytes en cada entorno. Obligatoria: sin ella el servidor no arranca.
- [ ] `COOKIE_SECURE`: sin definir o `1`. Con `0` el servidor no arranca.
- [ ] `STATE_STORAGE`: sin definir o `database`. Con `memory` el servidor no arranca.
- [ ] `FILE_STORAGE`: sin definir o `database`. Con `disk` el servidor no arranca.

### GitHub, repositorio BASE-DE-DATOS-ARQUILA

- [ ] Entorno `production` con al menos un revisor en *Required reviewers*. Sin revisores, GitHub no pide aprobación y `reset-demo.yml` carga el seed sin control.
- [ ] Un revisor disponible a diario: cada ejecución de las 08:00 UTC espera aprobación y, si nadie aprueba, la demo no se restaura.

### Orden de despliegue

1. BASE-DE-DATOS-ARQUILA: `feat/fase1` y las migraciones que falten (punto 3).
2. Variables de Vercel de este apartado, antes de desplegar el backend.
3. **BACKEND-ARQUILA y FRONTEND-ARQUILA de S4 juntos:** `POST /auth/register` responde 202 sin sesión, y solo `feat/fase1` del frontend inicia sesión después. Con un solo lado desplegado, crear una cuenta falla o no abre sesión.
4. Las ramas `feat/diseno-*` del frontend, después; no dependen del backend.

## 1. Orden de la fusión

- [ ] Primero BASE-DE-DATOS-ARQUILA (migraciones), luego BACKEND-ARQUILA y por último FRONTEND-ARQUILA.
- [ ] El backend no se despliega en producción hasta que las migraciones 012-027 estén aplicadas (punto 3).

## 2. Variables de Vercel (proyecto `arquila-backend`)

Revisar en Production **y** en Preview: Vercel define `VERCEL=1` en los dos, así que las previews también usan los valores de producción.

- [ ] `DATABASE_URL` apunta a la base correcta en cada entorno.
- [ ] `APP_URL` (y `CORS_ORIGINS` si hace falta) con la dirección de la interfaz.
- [ ] `COOKIE_SECURE`: sin definir o `1`. Nunca `0`.
- [ ] `STATE_STORAGE`: sin definir o `database`. Nunca `memory`.
- [ ] `FILE_STORAGE`: sin definir o `database`. Nunca `disk`.
- [ ] `COOKIE_SAMESITE=none` solo si la interfaz y la API están en sitios distintos (`*.vercel.app` lo son).
- [ ] `TRUST_PROXY_HEADERS=1` (necesario para la IP real, punto 5).
- [ ] `JWT_SECRET` de al menos 32 bytes, en Production y en Preview. Sin ella, o con otra variable insegura, **el servidor no arranca**.
- [ ] `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`; sin ellas la recuperación de contraseña responde 503.
- [ ] `REGISTRATION_LIMIT_PER_HOUR` solo si se quiere otro valor que 10.

## 3. Tablas y migraciones

En el repositorio, `git ls-tree origin/main migrations/` (BASE-DE-DATOS-ARQUILA, 24-10-2026) termina en `015_walkthrough_and_renovation.sql`: `main` tiene de la 001 a la 015 y `santiago` añade de la 016 a la 027. Eso dice qué hay en el repositorio, no qué está aplicado: el estado de la base de producción no se supone, se mira en su tabla `schema_migrations`.

- [ ] En la base de producción, `SELECT version FROM schema_migrations ORDER BY version;` y anotar la última aplicada y si falta alguna intermedia. No dar por aplicadas 012-015 por estar en `main`.
- [ ] Copia de seguridad (o rama de Neon) de producción antes de aplicar nada.
- [ ] Aplicar las que falten. `deploy.yml` solo corre al hacer push a `main` con cambios en `migrations/**` y espera la aprobación del entorno `production`; si faltan algunas de 012-015, que ya están en `main`, lanzarlo a mano desde «Actions» (`workflow_dispatch`).
- [ ] Después de aplicar, la misma consulta muestra de `001_initial_schema.sql` a `027_same_project_references.sql`: 27 filas.
- [ ] Existen `runtime_state` (011) y `file_contents` (010). Sin ellas el registro, el inicio de sesión, deshacer y la subida de archivos responden 500 y `/health` sigue respondiendo 200.
- [ ] La rama de Neon que usan las previews: misma consulta de `schema_migrations`, mismas 27 filas.
- [ ] Migration 028 (`activity_log`, R18): before applying it, run `SHOW TimeZone;` on that database. 028 reads the old timestamps in that zone (locally it was `America/Bogota`); if production is not UTC, confirm with the owner. Lock: `ACCESS EXCLUSIVE` on `activity_log` while it rewrites the table and its 3 indexes (proportional to the number of rows). Afterwards: 28 rows in `schema_migrations`. Rollback: `rollback/028_down.sql`.

## 4. A1: la demo en producción

`reset-demo.yml` carga `seed.sql` en producción todos los días, y desde `feat/fase1` con la aprobación que exige `deploy.yml`. Crea una cuenta con contraseña pública (`demo@example.com`).

- [x] La demo sigue en producción, con aprobación manual: `environment: production` en `reset-demo.yml` y README corregido (`feat/fase1` de BASE-DE-DATOS-ARQUILA).
- [ ] Revisores configurados (punto 0).

## 5. A8: el backend ve la IP real

El límite de registros por IP solo sirve si la dirección es la del usuario y no la del proxy de Vercel.

- [ ] En una preview, con `TRUST_PROXY_HEADERS=1`, registrar desde **dos redes distintas** (por ejemplo, la wifi de casa y los datos del móvil).
- [ ] Los registros de cada red cuentan por separado: agotar el límite en una red no bloquea la otra (429 solo en la primera). Para la prueba basta bajar `REGISTRATION_LIMIT_PER_HOUR` en la preview y volver a dejarlo después.
## 6. A4: valores seguros en producción

En una preview recién desplegada:

- [ ] Registro, inicio de sesión y deshacer responden sin 500.
- [ ] La cookie de sesión lleva `Secure` (y `SameSite` según el punto 2).
- [ ] Las respuestas llevan `Strict-Transport-Security: max-age=31536000`, sin `includeSubDomains` ni `preload`.
- [ ] El servidor arranca. Si no, el registro `insecure_setting` dice en `variable` cuál corregir.
- [ ] Subir un archivo, recargar y volver a abrirlo (comprueba `file_contents`).

## 7. Después de fusionar

- [ ] Repetir los puntos 5 y 6 en producción.
- [ ] Iniciar sesión desde la interfaz publicada y recorrer un proyecto.
