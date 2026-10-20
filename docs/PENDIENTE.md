# Pendiente

Funciones que la interfaz podría pedir y que el backend **no tiene**. No hay rutas que las simulen: si la interfaz las muestra, debe presentarlas como no disponibles. Para cada una se indica lo que haría falta para implementarla.

## Renderizado fotorrealista

Hoy el backend entrega la geometría (`/api/v1/rooms/{id}/mesh` y `/api/v1/spatial-data/scene`, en glTF o JSON) y la interfaz la dibuja en el navegador. No hay ningún motor que produzca imágenes fotorrealistas.

Haría falta:

- Un motor de render por trazado de rayos (por ejemplo Blender con Cycles en modo sin interfaz) que reciba el glTF de la escena, los materiales de superficie y los ajustes de `scene_settings` (iluminación y cámara).
- Un servidor con GPU, o mucho tiempo de CPU, fuera de Vercel: una función de Vercel no tiene GPU ni la duración necesaria.
- Una cola de trabajos, porque un render tarda de segundos a minutos: `POST /projects/{id}/renders` crearía el trabajo y `GET /renders/{id}` devolvería su estado y, al terminar, el archivo de imagen.
- Una tabla nueva (`render_jobs`: proyecto, cámara, estado, archivo resultado, error) en `BASE-DE-DATOS-ARQUILA`.
- Almacenamiento para las imágenes resultantes, que pesan más que el límite de 4,5 MB por petición de Vercel: un almacenamiento de objetos con enlaces firmados.
- Materiales con propiedades físicas (rugosidad, reflexión, texturas), que hoy son solo un nombre (`surface`).

## Análisis estructural

Los componentes estructurales (`/components`) son cajas con medidas y posición; el backend no calcula esfuerzos, cargas ni deformaciones, y no debe presentarse ningún resultado como verificación estructural.

Haría falta:

- Un motor de cálculo por elementos finitos o de pórticos (por ejemplo OpenSeesPy o PyNite) y un modelo analítico: nudos, barras, apoyos y uniones, que hoy no existen; las cajas actuales no dicen cómo se conectan.
- Propiedades de los materiales (módulo de elasticidad, resistencia, peso propio) y de las secciones.
- Cargas y combinaciones según la norma aplicable (en Ecuador, la NEC), incluido el sismo.
- Tablas nuevas para cargas, apoyos, casos de carga y resultados, y rutas para lanzar el cálculo y leerlo.
- Revisión por un profesional habilitado y un aviso claro de que el resultado no sustituye un cálculo firmado.

## Exportación a PDF en el servidor

No hay ninguna ruta que genere PDF. Hoy la única forma es imprimir desde el navegador.

Haría falta:

- Una librería de composición (WeasyPrint a partir de HTML, o ReportLab) añadida a `requirements.txt`, con sus dependencias del sistema (WeasyPrint necesita Pango) disponibles también en el despliegue.
- Plantillas del documento: portada (con `cover_file_id`), datos del proyecto, terrenos, cuadro de materiales con costos, planos y elevaciones.
- Dibujar los planos como SVG en el servidor, porque hoy los dibuja la interfaz.
- Una ruta `GET /projects/{id}/export.pdf`. Un PDF con imágenes puede superar los 4,5 MB que admite una respuesta de Vercel; en ese caso habría que guardarlo en un almacenamiento de objetos y devolver un enlace.

## Notificaciones de otros eventos

Hoy solo se crea la notificación del cambio de contraseña. Otros avisos útiles necesitan piezas que no existen:

- **Tareas próximas a vencer**: una tarea programada (por ejemplo un Cron Job de Vercel que llame a una ruta protegida una vez al día) que busque tareas con `due_date` cercana.
- **Cambios hechos por otra persona**: requiere proyectos compartidos (ver el punto siguiente).
- Las preferencias ya guardan `notifications` (`{clave: booleano}`), pero ningún aviso las consulta todavía; al añadir avisos habrá que respetarlas.

## Proyectos compartidos

Un proyecto solo es visible para su dueño. Por eso una tarea solo se puede asignar al dueño, aunque la tabla `tasks` tenga `assignee_id`. Para colaborar haría falta una tabla de miembros por proyecto con su rol, cambiar la comprobación de propiedad de `services/base.py` para que acepte miembros y decidir qué puede hacer cada rol.

## Avatar sin proyecto

`files.project_id` es obligatorio, así que el avatar tiene que ser una imagen subida a alguno de los proyectos del usuario. Para subirlo aparte (`POST /auth/me/avatar`) haría falta una migración que permita archivos sin proyecto (o una tabla propia) y adaptar las comprobaciones de propiedad de los archivos.

## Detalles conocidos

- Las migraciones `016` a `024` de `BASE-DE-DATOS-ARQUILA` existían en la carpeta local pero no estaban confirmadas en git al hacer este trabajo. La CI de este repositorio clona `BASE-DE-DATOS-ARQUILA` desde GitHub, así que el paso de pruebas con PostgreSQL fallará hasta que esas migraciones se suban.
- La migración `017` añade `created_by` y `updated_at` a casi todas las tablas. El backend solo rellena `created_by` en tareas y versiones; el resto queda vacío para las filas nuevas, y `updated_at` lo mantiene el disparador de la base.
- Las versiones no tienen límite de cantidad ni de tamaño. Con proyectos grandes convendría limitar cuántas se guardan o borrar las más antiguas.
- El historial de actividad no recoge los cambios hechos por `/api/v1` ni la generación automática de recomendaciones.
