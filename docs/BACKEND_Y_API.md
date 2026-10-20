# BACKEND Y API

Este documento explica las decisiones del backend. El código no lleva comentarios, así que el porqué de cada decisión está aquí.

Las decisiones de la interfaz (esquemas del terreno, planos, modelo 3D, estados de carga y accesibilidad) están en `FRONTEND-ARQUILA/docs/FRONTEND.md`.

## Capas

```text
api/           Recibe la petición HTTP y valida los datos (schemas).
services/      Lógica de negocio y control de permisos.
repositories/  Consultas a la base de datos.
models.py      Tablas (SQLAlchemy). Debe coincidir con BASE-DE-DATOS-ARQUILA/migrations/.
```

Los errores de negocio son excepciones propias (`errors.py`) que `main.py` convierte en respuestas HTTP:

| Código | Significado |
|---|---|
| 401 | No hay sesión o la sesión no es válida. |
| 404 | El recurso no existe o pertenece a otro usuario. |
| 409 | Conflicto: correo o nombre ya usados. |
| 413 | El archivo supera el tamaño máximo. |
| 415 | Tipo de archivo no admitido. |
| 400 | El enlace de recuperación de contraseña no es válido o caducó. |
| 422 | Los datos enviados no son válidos. |
| 429 | Demasiados intentos fallidos de inicio de sesión. |

## Patrón Adapter

El backend habla con dos servicios externos: el de IA y el de correo. Cada uno tiene su propia forma de llamarse, distinta de lo que la aplicación necesita. Para que los servicios de la aplicación no dependan de esas librerías, cada servicio externo se usa a través de un adaptador: una clase que ofrece la interfaz que la aplicación espera y la traduce a las llamadas de la librería.

| Interfaz que usa la aplicación | Adaptador | Qué adapta |
|---|---|---|
| `Assistant.reply(system, messages)` devuelve un texto | `OllamaAssistant` en `app/ai.py` | Un modelo local servido por Ollama, por HTTP: elige el modelo, envía la conversación, limpia la respuesta y convierte los fallos en `AIUnavailableError`. |
| `Mailer.send(recipient, subject, body)` | `SmtpMailer` en `app/mailer.py` | La librería `smtplib`: construye el mensaje, abre la conexión cifrada, se identifica y envía. |
| `Mailer.send(recipient, subject, body)` | `ConsoleMailer` en `app/mailer.py` | La consola del servidor, para desarrollo sin correo configurado. |

`AuthService` y `ConversationService` solo conocen las interfaces `Mailer` y `Assistant`. Gracias a eso:

- cambiar de proveedor de IA o de correo significa escribir otro adaptador, sin tocar los servicios;
- las pruebas sustituyen el adaptador por uno simulado y no llaman a ningún servicio real.

Las interfaces se declaran con `typing.Protocol`: cualquier clase que tenga el método con esa forma sirve, sin necesidad de heredar. Los adaptadores tienen sus pruebas en `tests/test_adapters.py`.

## Autenticación

- El registro y el inicio de sesión crean una sesión y la entregan en una cookie `HttpOnly` con `SameSite=Lax`. Al ser `HttpOnly`, el código de la página no puede leerla; al ser `SameSite=Lax`, otros sitios no pueden usarla para enviar peticiones de escritura.
- En la base solo se guarda el hash SHA-256 del identificador de sesión, de modo que una copia de la base no permite suplantar sesiones.
- Las contraseñas se guardan con Argon2id (librería `argon2-cffi`, con sus parámetros por defecto: 64 MiB de memoria, 3 pasadas y 4 hilos) y una sal aleatoria por contraseña. Es el algoritmo que recomienda OWASP como primera opción.
- Las cuentas creadas antes de este cambio tienen la contraseña guardada con `scrypt`. Siguen funcionando: en el primer inicio de sesión correcto, el backend vuelve a guardar la contraseña con Argon2id. Lo mismo ocurre si más adelante se endurecen los parámetros.
- Un inicio de sesión fallido devuelve el mismo mensaje exista o no el correo y realiza la misma verificación de contraseña en ambos casos, para no revelar qué cuentas existen.
- La sesión dura 7 días y se elimina del servidor al cerrar sesión.
- `POST /auth/change-password` exige la contraseña actual, guarda la nueva con Argon2id y cierra todas las demás sesiones de la cuenta; la que hace la petición sigue abierta. Una contraseña actual incorrecta responde 422 y no 401, para que la interfaz no lo tome por una sesión caducada. Tras 5 fallos en 15 minutos responde 429; el control es el mismo que el del inicio de sesión, por usuario, y se guarda en `runtime_state` con `STATE_STORAGE=database`.
- En producción hay que definir `COOKIE_SECURE=1` para que la cookie solo viaje por HTTPS.
- `SameSite` se puede cambiar con `COOKIE_SAMESITE` (`lax`, `strict` o `none`). `none` solo hace falta si la interfaz y la API están en sitios distintos: el navegador exige entonces HTTPS, así que la cookie se marca `Secure` aunque `COOKIE_SECURE` valga `0`. Con `none` se pierde la protección de `SameSite` frente a peticiones de escritura desde otros sitios; las peticiones con cuerpo JSON siguen bloqueadas por CORS, pero la subida de archivos y el cierre de sesión no llevan esa barrera.

- Tras 5 intentos fallidos con el mismo correo en un minuto, el inicio de sesión responde 429 hasta que los intentos salen de esa ventana de tiempo. Un inicio de sesión correcto borra la cuenta de fallos. El control usa la cola de `app/data_structures` (ver `05_COMPLEJIDAD.md`) y vive en memoria, igual que el historial de deshacer.
- El control recuerda como máximo 10 000 correos a la vez; al llegar a ese número descarta los que ya caducaron, para que no pueda crecer sin límite.
- El límite se cuenta por correo, no por dirección IP: alguien que conozca un correo puede bloquear su inicio de sesión durante un minuto escribiendo contraseñas falsas.

### Recuperación de contraseña

- «Olvidé mi contraseña» pide un correo. Si existe una cuenta, se genera un enlace válido 30 minutos y de un solo uso; la respuesta es la misma exista o no la cuenta, para no revelar qué correos están registrados.
- En la base solo se guarda el hash del identificador del enlace. Pedir un enlace nuevo invalida el anterior.
- Al cambiar la contraseña se cierran todas las sesiones abiertas de esa cuenta.
- El correo se envía por SMTP si están definidas `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` y `SMTP_FROM`. Si `SMTP_HOST` no está definida, el mensaje con el enlace se escribe en la consola del servidor: sirve para desarrollo, pero en producción hay que configurar el correo.
- `APP_URL` indica la dirección de la aplicación que se pone en el enlace.
- Se atienden como máximo 3 solicitudes por correo cada 15 minutos; las demás se ignoran sin avisar, con la misma respuesta. Usa el mismo control basado en la cola que el inicio de sesión.
- El envío real por SMTP no está probado: las pruebas usan un envío simulado.

## Proyectos, versiones e historial

El contrato de estas rutas, para la interfaz, está en `API_CONTRATO.md`. Las decisiones:

- **Lista compatible**: `GET /projects` sigue devolviendo la lista de siempre; solo `page` o `page_size` la convierten en una página con `total`. Así la interfaz actual no cambia y la nueva puede pedir páginas. El total viaja además en `X-Total-Count`.
- **Archivar**: `archived_at` y `status = 'archived'` se mantienen a la vez, se archive con `POST /archive` o con `PATCH`. Al desarchivar se recupera el estado anterior, que queda guardado en el historial de la acción `archived`.
- **Versiones y duplicado** comparten `services/project_snapshot.py`: el contenido del proyecto se copia a un documento JSON con los mismos ayudantes que «Deshacer» (`column_values`, `encode_values`) y se vuelve a crear fila a fila. Los identificadores cambian, así que los cuartos y componentes van dentro de su plano y los vértices dentro de su terreno. Los archivos no se copian; solo se conserva la referencia mientras el archivo siga en el proyecto. Restaurar guarda antes el estado actual como otra versión y vacía el historial de «Deshacer».
- **Historial**: cada servicio registra en `activity_log` lo que crea, edita o elimina (`ProjectScopedService._record`). La entrada se escribe después de confirmar el cambio, así que un fallo del registro nunca deshace el cambio, pero en ese caso raro el cambio quedaría sin entrada.
- **Resumen**: «en progreso» son los proyectos `active` no archivados con avance menor que 100; «completados», los que tienen avance 100.

## Permisos

Todo lo que pertenece a un proyecto exige sesión y que el proyecto sea del usuario. Un proyecto ajeno responde 404, igual que uno inexistente, para no revelar qué identificadores existen. La comprobación está centralizada en `services/base.py`.

## API v1: unidades, datos espaciales y corrida de interior

Las rutas nuevas viven bajo `/api/v1` y conviven con las anteriores, que no cambian.

| Ruta | Operaciones | Permiso |
|---|---|---|
| `/api/v1/properties`, `/api/v1/units` | Listar, crear, leer, editar y eliminar propiedades y unidades. | `units:read`, `units:write` |
| `/api/v1/rooms` | Listar y leer los cuartos con su unidad, categoría y malla; `PATCH` cambia esos tres datos. Crear y eliminar cuartos sigue en las rutas anteriores, que tienen «Deshacer». | `rooms:read`, `rooms:write` |
| `/api/v1/spatial-data` | `GET` devuelve en una sola respuesta los elementos del proyecto y el recuento por capa; admite `layer`, `room_id`, `work_status` y `bbox=min_x,min_y,max_x,max_y`. `/elements` crea, edita y elimina; `/import` carga un documento externo; `/providers` lista los formatos. | `spatial:read`, `spatial:write` |
| `/api/v1/rooms/{id}/mesh`, `/api/v1/spatial-data/scene` | Devuelven la geometría de un cuarto, o del proyecto entero, con sus elementos espaciales. `format=gltf` (por defecto) entrega un glTF 2.0 autocontenido; `format=json`, una lista de cajas. | `rooms:read`, `spatial:read` |
| `/api/v1/interior-walkthrough` | `GET` devuelve los pasos en orden y el registro de obras. `/steps` y `/logs` crean, editan y eliminan. Un paso puede llevar en `view_config.camera` la posición y el objetivo de la cámara, en metros del plano (`[x, y, z]`). | `walkthrough:read`, `walkthrough:write` |
| `/api/v1/renovations/logs` | El mismo registro de obras, servido también por separado. | `walkthrough:read`, `walkthrough:write` |
| `/api/v1/auth/token`, `/api/v1/auth/me` | Emitir un token de acceso y consultar los roles y permisos propios. | — |
| `/api/v1/users/{id}/roles` | Asignar roles a un usuario. | `roles:manage` |

- **Mensajes en español**: en estas rutas el `detail` de los errores y los mensajes de validación ya llegan en español (`api/v1/validation.py`), con la misma forma que usa FastAPI. Las rutas anteriores siguen respondiendo en inglés y la interfaz las traduce.
- **Roles**: cada operación exige un permiso (`require(...)` en `api/deps.py`) además de que el proyecto sea del usuario; sin el permiso responde 403. Los roles y sus permisos se leen de la base de datos. Quien se registra recibe el rol `architect`. Ningún rol da acceso a proyectos ajenos. El primer `admin` se asigna en la base de datos; no hay pantalla para administrar roles.
- **Token de acceso (JWT)**: `POST /api/v1/auth/token` recibe correo y contraseña y devuelve un token HS256 válido 15 minutos, que se envía como `Authorization: Bearer ...`. Solo sirve en `/api/v1`, deja de valer si el usuario cambia la contraseña y comparte el límite de intentos del inicio de sesión. Si `JWT_SECRET` no está definida o tiene menos de 32 bytes, la ruta responde 503. La interfaz web no lo usa: sigue con la cookie de sesión, que el navegador no deja leer a los scripts.
- **Adaptadores de formatos 3D** (`app/providers/`): `SpatialDataProvider` es la interfaz y cada formato externo tiene un adaptador que lo convierte en borradores de elementos. `gltf` lee la parte JSON de un glTF 2.0 (un elemento por nodo con malla; la caja sale de los `min` y `max` del atributo `POSITION`, con las transformaciones de los nodos, y pasa de «Y hacia arriba» a las coordenadas del plano). `native` lee una lista de elementos con sus cajas. Añadir otro formato es escribir un adaptador y registrarlo en `providers/__init__.py`. No hay adaptador para DWG, IFC ni Revit.
- **Patrón Bridge en las escenas** (`app/scenes/`): separa *qué* se dibuja de *cómo* se escribe. De un lado están las escenas (`RoomScene`, `ProjectScene`), que deciden con las reglas del negocio qué cuartos y elementos entran; del otro, los codificadores (`JsonSceneEncoder`, `GltfSceneEncoder`). Una escena recibe su codificador al crearse, así que añadir un formato no toca las escenas ni añadir una escena toca los formatos. El glTF que se exporta se puede volver a importar con el adaptador `gltf` y conserva las medidas.

## Archivos

- Por defecto se guardan en disco, en la carpeta indicada por `UPLOAD_DIR`, con un nombre aleatorio. El nombre original solo se guarda como texto para mostrarlo; nunca decide dónde se escribe el archivo.
- El tipo se detecta por los primeros bytes del contenido, no por la extensión ni por lo que declare el navegador. Se admiten PDF, PNG, JPEG y WebP, hasta 20 MB.
- Al eliminar un archivo se desvincula de forma explícita de los planos y elevaciones que lo usaban. No se depende de `ON DELETE SET NULL` porque SQLite, que se usa en las pruebas, solo lo aplica si se activan las claves foráneas.
- Al eliminar un proyecto se borran también sus archivos del disco.
- Con `FILE_STORAGE=database` el contenido se guarda en la tabla `file_contents` de PostgreSQL en lugar del disco. Existe para los alojamientos que no conservan el disco entre peticiones, como Vercel. Las comprobaciones de tipo y de tamaño son las mismas, y el contenido se borra con su archivo. Los archivos que ya estaban en disco se siguen sirviendo desde ahí. Guardar binarios en la base es aceptable para archivos pequeños y pocos usuarios; con más volumen convendría un almacenamiento de objetos.
- El botón «Ver», en la pestaña Archivos y junto al archivo adjunto de un plano o una elevación, abre el archivo dentro de la aplicación en una ventana superpuesta (`FRONTEND-ARQUILA/src/components/FileViewer.tsx` y `Modal.tsx`): las imágenes se muestran ajustadas a la ventana y los PDF con el lector del navegador. La ventana usa el elemento `<dialog>` del navegador, así que se cierra con Escape, con el botón «Cerrar» o pulsando fuera, y tiene un enlace para abrir el archivo en otra pestaña.

## Deshacer eliminaciones

- Se guarda un historial por proyecto de los terrenos, planos, elevaciones, materiales, cuartos y componentes estructurales eliminados, con un máximo de 20 entradas.
- Un cuarto o un componente pertenece a un plano. Si su plano ya no existe al restaurarlo, se responde 409 y la entrada se descarta, para que no bloquee las anteriores: un plano restaurado tiene otro identificador, así que esa entrada ya no se podría recuperar nunca.
- El historial usa la lista doblemente enlazada de `app/data_structures` (ver `05_COMPLEJIDAD.md`).
- Por defecto vive en memoria: se pierde al reiniciar el servidor y no se comparte entre varios procesos.
- Con `STATE_STORAGE=database` el historial se guarda además en la tabla `runtime_state`, una fila por proyecto con su contenido en JSON. En cada operación se carga de la base a la lista doblemente enlazada y a la pila, se opera sobre ellas igual que en memoria y se vuelve a guardar. Las estructuras siguen siendo las que deciden qué se deshace y qué se rehace; la base solo conserva su contenido entre peticiones. Existe para alojamientos como Vercel, donde cada petición puede caer en un proceso distinto. La fila se lee con bloqueo (`SELECT ... FOR UPDATE`), de modo que dos peticiones simultáneas sobre el mismo proyecto o el mismo correo esperan su turno en lugar de pisarse; SQLite, que se usa en las pruebas, ignora ese bloqueo.
- Al restaurar se inserta una fila nueva con los mismos datos; el identificador cambia porque el anterior pudo haberse reutilizado.
- Si al restaurar hay un conflicto (por ejemplo, ya existe un material con ese nombre), se responde 409 y la entrada se conserva.
- Si el archivo adjunto de un plano ya no existe, el plano se restaura sin archivo.

## Recomendaciones automáticas

`POST /projects/{id}/recommendations/generate` revisa los terrenos y materiales con reglas fijas (`services/recommendation_rules.py`) y reemplaza las recomendaciones automáticas anteriores, sin tocar las manuales. No usa IA; se guardan con origen `system`.

Las reglas son orientativas (por ejemplo, avisar cuando la pendiente es de 15 % o más) y no sustituyen un estudio técnico. Los textos están en español porque se muestran al usuario.

Cada recomendación lleva una prioridad: `high`, `medium` o `low`. Cada regla fija la suya (una pendiente fuerte o un suelo arcilloso son de prioridad alta; un material con cantidad cero, baja) y las manuales la eligen al crearse, con `medium` por defecto. La pantalla las ordena de mayor a menor prioridad. La prioridad la validan el esquema (422) y la base de datos (`CHECK`).

## Asistente de IA

- El proveedor de IA es un modelo local servido por [Ollama](https://ollama.com), que es gratuito y no necesita clave. Se usa a través de su adaptador.
- `GET /assistant/status` dice quién responderá ahora: `ollama` (con el nombre del modelo) o `rules` si no hay IA disponible. La pestaña Asistente lo muestra en la línea «Ahora responde». Se comprueba al abrir la pestaña; si Ollama se enciende o se apaga después, la línea no cambia hasta volver a entrar, aunque cada respuesta sigue llevando su origen real.
- En cada pregunta se envían los datos del proyecto y los últimos 20 mensajes de la conversación. Los totales de costo van ya calculados, para que el modelo los cite en lugar de calcularlos.
- La pestaña ofrece cuatro preguntas sugeridas que se envían con un clic. Son texto fijo del frontend y siguen el mismo camino que una pregunta escrita. Si hay un elemento seleccionado en el modelo 3D de ese proyecto, aparece antes una quinta pregunta sobre él, con su tipo, nombre, medidas y plano escritos en el texto, porque el backend no le pasa al asistente los cuartos ni los componentes.
- Cada llamada tiene un tiempo máximo de espera: 120 segundos para la respuesta y 1 segundo para conectar con Ollama. Si se agota el tiempo, el asistente contesta con las reglas.
- La llamada real a la IA no está cubierta por pruebas automáticas: las pruebas usan un asistente simulado y un servidor de Ollama simulado, de modo que no necesitan red. Cubren también los tiempos de espera agotados.

### Privacidad

Qué sale del equipo depende de quién responde:

- **Ollama.** El modelo corre en el propio equipo: nada sale de él.
- **Reglas.** Se calculan en el backend, sin llamar a ningún servicio.

La pestaña del asistente indica en «Ahora responde» cuál de los dos está activo.

### Modelo local con Ollama

No hay que configurar nada en `.env`. Pasos, una sola vez:

1. Instalar Ollama desde https://ollama.com.
2. Descargar un modelo: `ollama pull llama3.2` (unos 2 GB). Los modelos más pequeños, como `llama3.2:1b`, se inventan cifras del proyecto.

Con Ollama encendido, el asistente lo encuentra en `http://127.0.0.1:11434` y usa el primer modelo instalado. Dos variables opcionales cambian eso: `OLLAMA_MODEL` fija el modelo y `OLLAMA_URL` la dirección.

- La velocidad y la calidad de las respuestas dependen del equipo y del modelo; un modelo pequeño responde peor que uno grande.
- Probado el 3 de octubre de 2026 con Ollama 0.35.1 y `llama3.2:1b` (1,3 GB): la conexión funciona y las respuestas quedan guardadas con origen `ai`. La primera respuesta tardó cerca de un minuto, mientras se cargaba el modelo; las siguientes, unos dos segundos. Pero ese modelo no es fiable con los datos: acertó la pendiente del terreno y se inventó el costo total de los materiales y el nombre de un plano. Con un modelo tan pequeño, las reglas dan cifras más fiables.
- Probado el mismo día con `llama3.2` (2 GB) y las mismas tres preguntas: acertó la pendiente, el costo total y el detalle de los materiales, y el plano registrado. Es el modelo recomendado; se fija con `OLLAMA_MODEL=llama3.2`. Sigue siendo un modelo pequeño y redacta con alguna imprecisión.
- Los modelos pequeños fallan al hacer cuentas: en un proyecto con ocho materiales, `llama3.2` dio bien el costo total pero señaló como más caro un material que no lo era, con una cifra mal multiplicada. Por eso el backend no le deja calcular: los datos que recibe llevan ya el costo de cada material, el total y el nombre del más caro, con los materiales ordenados de mayor a menor costo, y las instrucciones le piden citar esas cifras tal cual. Con ese cambio, la misma pregunta se respondió bien.
- Si Ollama no está encendido o no tiene modelos, el backend lo detecta en un segundo como máximo y contesta con las reglas. Después no vuelve a intentar la conexión durante 30 segundos.
- Algunos modelos escriben su razonamiento entre etiquetas `<think>`; el adaptador lo quita de la respuesta.

### Respaldo por reglas

Si el proveedor no está disponible (Ollama apagado o sin modelos), o la llamada a la IA falla (error del servicio o de red), el asistente no devuelve un error: contesta con reglas fijas (`services/assistant_rules.py`) sobre los datos del proyecto.

- Las reglas buscan palabras clave en la pregunta y reconocen tres temas: terreno (área, pendiente, desnivel, suelo), materiales y costos, y planos y elevaciones. Una pregunta puede tocar varios temas. Si no reconoce ninguno, resume el proyecto y dice sobre qué puede responder.
- Reutilizan los avisos de `services/recommendation_rules.py`, para que el asistente y las recomendaciones automáticas digan lo mismo.
- Cada mensaje del asistente guarda su origen en el campo `source`: `ai` si lo escribió la IA, `rules` si salió de las reglas. Los mensajes del usuario lo tienen vacío. La interfaz marca las respuestas por reglas con la etiqueta «Respuesta por reglas».
- No entienden el lenguaje: solo comparan palabras. Sirven para que el asistente sea útil sin IA, no para sustituirla.

## Cuartos

Un cuarto pertenece a un plano y se gestiona en la pestaña Modelo 3D (`FRONTEND-ARQUILA/src/components/RoomsPanel.tsx`). Las rutas siguen el mismo patrón que los planos: `POST` y `GET /projects/{id}/rooms`, y `GET`, `PATCH` y `DELETE /rooms/{id}`.

- Un cuarto es una caja: nombre, posición (`x_m`, `y_m`), ancho, largo y alto, en metros. La posición es la esquina del cuarto medida desde la esquina de origen del primer terreno del modelo.
- El plano de un cuarto debe ser del mismo proyecto; si no, se responde 404, igual que con el archivo de un plano.
- Las medidas deben ser mayores que cero. Lo validan el esquema (422) y la base de datos (`CHECK`).
- Al eliminar un plano o un proyecto se eliminan sus cuartos.

Simplificaciones:

- Los cuartos no entran en el historial de deshacer; por eso la interfaz pide confirmación antes de eliminar uno. Al deshacer la eliminación de un plano se recupera el plano, pero no sus cuartos.
- No se comprueba que un cuarto quede dentro del terreno ni que dos cuartos no se solapen.
- No hay puertas ni ventanas.

## Componentes estructurales

Las columnas, vigas y muros se gestionan en la pestaña Modelo 3D (`FRONTEND-ARQUILA/src/components/ComponentsPanel.tsx`), con las rutas `POST` y `GET /projects/{id}/components` (con filtro opcional `?kind=`) y `GET`, `PATCH` y `DELETE /components/{id}`.

- Un componente es una caja, igual que un cuarto, más un tipo (`kind`): `column`, `beam` o `wall`. Reutiliza la posición y las medidas del cuarto, así que no hay una tabla ni un formulario distinto por tipo. El formulario propone medidas habituales al elegir el tipo (columna de 0,3 × 0,3 × 3 m, viga de 4 × 0,3 × 0,4 m, muro de 4 × 0,2 × 3 m).
- El tipo lo validan el esquema (422) y la base de datos (`CHECK`).
- Valen las mismas reglas que en los cuartos: el plano debe ser del proyecto, las medidas deben ser mayores que cero y los componentes se eliminan con su plano o su proyecto.

Simplificaciones:

- Una caja solo puede ir alineada con los ejes: no hay muros ni vigas en diagonal. Un muro a lo largo de `y` se escribe con el ancho pequeño y el largo grande.
- No hay cálculo estructural (cargas, secciones, materiales): los componentes se registran y se dibujan, nada más.
- No entran en el historial de deshacer, igual que los cuartos.

## Proyectos de ejemplo

La página Proyectos ofrece cuatro ejemplos: Casa Familiar Andina, Vivienda compacta, Edificio multifamiliar y Oficina profesional. `GET /templates` los lista y `POST /templates/{id}/projects` crea un proyecto del usuario con su terreno, un plano por nivel, los cuartos de cada nivel y cuatro columnas en las esquinas de cada planta. El frontend abre el proyecto recién creado en la pestaña Modelo 3D.

- Los ejemplos están definidos en el código (`app/services/project_templates.py`), no en la base de datos: son pocos, fijos e iguales para todos los usuarios. Cada fila de cuartos se escribe con una función que los coloca uno a continuación del otro, así que no hay coordenadas repetidas a mano.
- El proyecto se crea en una sola transacción: si algo falla, no queda un proyecto a medias.
- Como el nombre de un proyecto es único por usuario, si ya existe se añade un número: «Vivienda compacta (2)».
- El proyecto creado es uno normal: se edita, se borra y se consulta igual que los demás.
- Una prueba comprueba, para cada ejemplo, que los cuartos caben en el lote y no se solapan.

Simplificaciones: solo «Vivienda compacta» trae materiales (ocho, con cantidad y costo); los demás ejemplos no. Ninguno trae elevaciones ni archivos, y las distribuciones son esquemáticas (filas de cuartos rectangulares), no planos de una obra real.

## Datos numéricos

La API recibe y devuelve áreas, cantidades y costos como números JSON. En la base de datos son `NUMERIC`.

## Rendimiento

Revisión hecha el 3 de octubre de 2026: se contó cuántas consultas a la base de datos hace cada endpoint con pocos datos (2 proyectos de 2 elementos) y con más (20 proyectos de 20 elementos). Si el número crece con los datos, hay una consulta repetida por cada elemento.

- Todas las listas hacen un número fijo de consultas, entre 3 y 5, sea cual sea la cantidad de datos.
- Se corrigió la lista de terrenos, que hacía una consulta más por cada terreno para traer sus vértices: con 20 terrenos pasaba de 6 a 24 consultas. Ahora trae los vértices de todos en una sola consulta y se queda en 5. Una prueba comprueba que el número no cambia al añadir terrenos.
- Se corrigió una espera en el asistente: sin Ollama encendido, cada pregunta perdía un segundo intentando conectar. Ahora, tras un intento fallido, el backend no vuelve a intentarlo durante 30 segundos y responde con las reglas de inmediato. La contrapartida es que, al encender Ollama, el asistente puede tardar hasta 30 segundos en notarlo.
- Generar recomendaciones y eliminar un proyecto sí hacen más consultas cuantos más elementos hay, porque escriben o borran una fila por elemento. Son operaciones poco frecuentes y no se cambiaron.
- El frontend compilado pesa unos 200 kB (62 kB comprimido), sin librerías de gráficos: los esquemas son SVG hechos a mano.

Las medidas se hicieron con una base SQLite en memoria; cuentan consultas, no tiempos reales contra PostgreSQL.

## Seguridad

Lo que protege cada parte está explicado en su sección: contraseñas, sesiones y límite de intentos en «Autenticación», acceso a los datos en «Permisos» y subida de archivos en «Archivos». Esta sección reúne lo que es común a toda la API y el resultado de la revisión del 4 de octubre de 2026.

### Cabeceras de respuesta

Todas las respuestas llevan estas cabeceras, que añade un middleware en `app/main.py`:

| Cabecera | Para qué |
|---|---|
| `X-Content-Type-Options: nosniff` | El navegador respeta el tipo declarado y no intenta adivinar otro. |
| `Referrer-Policy: no-referrer` | Al seguir un enlace no se envía la dirección de origen. |
| `Cache-Control: no-store` | Los datos de un usuario no quedan guardados en la caché del navegador ni de un intermediario. |
| `Content-Security-Policy: frame-ancestors` | Solo la propia aplicación (los orígenes de `CORS_ORIGINS` o `APP_URL`) puede mostrar una respuesta dentro de un marco. |
| `Permissions-Policy: camera=(), microphone=(), geolocation=()` | La API no necesita cámara, micrófono ni ubicación, así que ninguna respuesta puede pedirlos. |
| `Strict-Transport-Security` | Solo con `COOKIE_SECURE=1`: el navegador recordará durante un año que el sitio solo se usa por HTTPS. Sin HTTPS no se envía, para no dejar inservible una instalación local. |

No se envía `Cross-Origin-Resource-Policy`: en Vercel la interfaz y la API están en sitios distintos (`vercel.app` es un sufijo público) y esa cabecera impediría mostrar las imágenes de los archivos.

### Enlace de recuperación

El enlace de recuperación lleva su identificador en la dirección. La aplicación lo lee al abrir y lo quita de la barra de direcciones enseguida, para que no quede en el historial del navegador, y la página declara `referrer` `no-referrer` para que no viaje a otros sitios. Si se recarga la página antes de cambiar la contraseña hay que volver a abrir el enlace del correo.

### Tamaño de los datos

Todos los textos que recibe la API tienen una longitud máxima, las listas de vértices un número máximo de puntos y los archivos un tamaño máximo. La descripción de un proyecto admite hasta 2000 caracteres.

### Dependencias

Revisadas el 4 de octubre de 2026 con `npm audit` (frontend) y `pip-audit` (backend): sin vulnerabilidades conocidas. `pip-audit` señaló una en `pytest` 8, que solo se usa para las pruebas; `requirements-dev.txt` exige ahora `pytest` 9.0.3 o posterior.

### Registro de eventos

El backend escribe en la salida estándar una línea en formato JSON por cada evento (`app/logs.py`), para que se pueda filtrar o enviar a otra herramienta sin interpretar texto libre:

```json
{"time": "2026-10-04T20:54:46.650+00:00", "level": "info", "event": "request", "method": "POST", "path": "/auth/login", "status": 401, "duration_ms": 86.0}
```

| Evento | Cuándo |
|---|---|
| `request` | Cada petición atendida, con método, ruta, código de respuesta y duración. |
| `request_failed` | Una petición terminó con un error no previsto; incluye la traza. |
| `login_failed` | Inicio de sesión con credenciales incorrectas. |
| `login_blocked` | Inicio de sesión rechazado por el límite de intentos. |
| `password_rehashed` | Una contraseña antigua se volvió a guardar con Argon2id. |
| `assistant_fallback` | La IA no respondió y contestaron las reglas; incluye el motivo. |

No se registran contraseñas, correos, cookies ni los parámetros de la dirección: de cada petición solo queda la ruta. `LOG_LEVEL` fija el nivel mínimo (`INFO` por defecto). Para no duplicar líneas, `python -m app.dev` desactiva el registro de accesos propio de Uvicorn.

### Limitaciones conocidas

- El límite de intentos de inicio de sesión se cuenta por correo, no por dirección IP, y por defecto vive en memoria: se reinicia al reiniciar el servidor y no se comparte entre varios procesos (con `STATE_STORAGE=database` los intentos se guardan en la tabla `runtime_state` y la cola se reconstruye en cada petición).
- El registro no tiene límite de solicitudes y responde que un correo ya está registrado, así que permite averiguar si un correo tiene cuenta.
- La documentación automática de la API (`/docs`) queda accesible sin sesión. No muestra datos, solo la lista de operaciones.
- No hay un límite de archivos por proyecto, solo de tamaño por archivo.
- La aplicación no fuerza HTTPS: en un despliegue real debe ir detrás de un servidor que lo haga, con `COOKIE_SECURE=1`.

## Variables de entorno

Se pueden definir en la terminal o en el archivo `.env`, que leen `python -m app.dev`, `python -m app.migrate` y `python -m app.check`. Una variable ya definida en la terminal tiene prioridad sobre el archivo. `.env` está excluido del repositorio porque contiene contraseñas.

| Variable | Uso |
|---|---|
| `DATABASE_URL` | Conexión a la base de datos (obligatoria). |
| `DATABASE_DIR` | Carpeta del repositorio `BASE-DE-DATOS-ARQUILA`, de donde salen las migraciones (por defecto la carpeta hermana `../BASE-DE-DATOS-ARQUILA`). |
| `API_HOST`, `API_PORT` | Dirección y puerto en los que escucha la API (por defecto `127.0.0.1` y `8000`). |
| `UPLOAD_DIR` | Carpeta de archivos subidos (por defecto `uploads`). |
| `STATE_STORAGE` | `memory` (por defecto) guarda en memoria el historial de «Deshacer» y los límites de intentos; `database` los guarda en la tabla `runtime_state`. En producción hay que usar `database`. |
| `FILE_STORAGE` | `disk` (por defecto) guarda los archivos en `UPLOAD_DIR`; `database` los guarda en la tabla `file_contents`. |
| `COOKIE_SECURE` | `1` para exigir HTTPS en la cookie de sesión. |
| `JWT_SECRET` | Clave de al menos 32 bytes para firmar los tokens de acceso de `/api/v1/auth/token`. Sin ella no se emiten tokens; el resto de la API funciona igual. |
| `COOKIE_SAMESITE` | `lax`, `strict` o `none` (por defecto `lax`). `none` permite usar la sesión desde otro sitio y obliga a HTTPS. |
| `LOG_LEVEL` | Nivel mínimo del registro de eventos: `DEBUG`, `INFO`, `WARNING` o `ERROR` (por defecto `INFO`). |
| `OLLAMA_MODEL` | Modelo local que usa el asistente (por defecto, el primero instalado). |
| `OLLAMA_URL` | Dirección de Ollama (por defecto `http://127.0.0.1:11434`). |
| `APP_URL` | Dirección de la aplicación, para el enlace del correo de recuperación. También es el origen que CORS admite si no se define `CORS_ORIGINS`. |
| `CORS_ORIGINS` | Orígenes que pueden llamar a la API desde el navegador, separados por comas (por defecto, `APP_URL`). |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Servidor de correo para la recuperación de contraseña. |

### Comprobar los servicios externos

Después de escribir la clave de IA o los datos del correo en `.env`, este comando comprueba que funcionan de verdad, sin arrancar el servidor:

```bash
python -m app.check correo@ejemplo.com
```

Hace una pregunta corta al asistente y envía un mensaje de prueba a la dirección indicada. Por cada servicio escribe `OK` o `FAILED` con el motivo (falta la variable, no se pudo conectar). Sin dirección, solo comprueba el asistente. La pregunta al asistente es una llamada real a Ollama, que no cuesta nada.
