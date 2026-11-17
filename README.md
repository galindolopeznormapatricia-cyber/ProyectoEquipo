# DevProject Manager

Aplicación local para gestionar proyectos, equipo, tareas, horas e informes con
perfiles de Project Manager, desarrollador y cliente.

## Requisitos

- Python 3.10 o posterior.
- Las dependencias de `requirements.txt`.

## Preparar el entorno

Desde PowerShell, en la carpeta del proyecto:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Antes de ejecutar la aplicación, crea un `.env` con una clave secreta de al
menos 32 caracteres. Puedes generar una con:

```powershell
python -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))"
```

Copia la línea generada en `.env`. No compartas ni subas ese archivo al
repositorio; está excluido de Git.

La aplicación crea las tablas que falten al iniciar. También puedes
inicializarlas manualmente:

```powershell
python -m flask --app app init-db
```

## Crear la cuenta de Project Manager

El registro público crea cuentas de desarrollador. Para crear la primera cuenta
administradora, agrega estas variables a `.env` (el archivo está excluido de Git):

```dotenv
ADMIN_EMAIL=manager@ejemplo.com
ADMIN_PASSWORD=UnaClaveSegura1!
ADMIN_NAME=Project Manager
```

La contraseña debe tener al menos 10 caracteres, mayúscula, minúscula, número y
símbolo. Crea la cuenta con:

```powershell
python -m flask --app app seed-admin
```

Si ya existe la cuenta pero no recuerdas la contraseña o está desactivada,
ejecuta el comando de recuperación. Puedes indicar el correo que quieres
recuperar para no depender de `ADMIN_EMAIL`; en ese caso, te pedirá la contraseña
nueva de forma oculta:

```powershell
python -m flask --app app restaurar-admin manager@ejemplo.com
```

Después inicia sesión con el correo indicado y la nueva contraseña. Sin indicar
un correo, el comando usa `ADMIN_EMAIL` y `ADMIN_PASSWORD` de `.env` (o solicita
una contraseña nueva si la configurada no cumple la política). El comando nunca
muestra la contraseña en pantalla.

## Ejecutar la aplicación

```powershell
python app.py
```

Abre `http://127.0.0.1:5000`. La base SQLite se guarda en `instance/devproject.db`.
Los enlaces de recuperación se registran en la terminal en modo local; para
producción debe configurarse un servicio de correo y un servidor WSGI.

## Perfiles

- **Project Manager / Administrador:** administra usuarios, proyectos,
  presupuestos en MXN, estados e integrantes; puede crear y asignar tareas.
- **Desarrollador / Miembro de equipo:** consulta sus proyectos, crea y actualiza
  tareas, y reporta horas y notas de avance.
- **Cliente / Stakeholder:** consulta el resumen, estado, fechas y métricas de los
  proyectos asignados; no accede a las tareas internas ni modifica información.

Los clientes y desarrolladores solo pueden acceder a los proyectos a los que
están asignados. Las operaciones que modifican datos requieren token CSRF.

## Gestión de proyectos y tareas

- Los proyectos incluyen objetivos, fechas, presupuesto, estado y equipo con un
  rol específico por integrante.
- Cada proyecto puede dividirse en fases o hitos ordenados, con entregables y
  fechas; las tareas pueden asociarse a una fase.
- Las tareas se filtran por estado, responsable y fase. Su formulario registra
  horas planificadas, mientras que los integrantes reportan las horas reales.
- Al iniciar, la aplicación agrega de forma compatible las columnas nuevas a la
  base SQLite existente y conserva proyectos, tareas y reportes previos.

## Hito 3 - Gestión de tareas y estimación de tiempos

- **CRUD de tareas:** crear, consultar, editar y eliminar tareas con título,
  descripción, estado, prioridad y fecha límite. Al eliminar una tarea se
  eliminan también sus registros de horas.
- **Responsables y fases:** asignación a desarrolladores activos del proyecto y
  vinculación opcional con una fase del mismo proyecto. Eliminar una fase
  conserva las tareas y sus horas, dejándolas sin fase.
- **Estimación y ejecución:** horas planificadas entre 0 y 99,999.99 por tarea;
  reportes de horas reales mayores a 0 y de hasta 24 horas por registro, con
  fecha y nota de avance opcionales. Ambos valores admiten como máximo dos
  decimales; los valores inválidos se rechazan sin redondearlos.
- **Registro de horas:** los desarrolladores integrantes pueden reportar en
  tareas sin responsable o asignadas a ellos, siempre que no estén completadas.
  Los administradores pueden consultar el historial de reportes.
- **Seguimiento:** comparación de horas planificadas, reales y desviación en
  tareas, fases y resumen del proyecto; informe comparativo entre proyectos.
  La desviación se calcula como reales menos planificadas: un valor positivo
  indica exceso y uno negativo indica horas aún disponibles, no ahorro
  definitivo. El avance es el porcentaje de tareas completadas y no depende
  de las horas consumidas. Los filtros de tareas no alteran los totales.
- **Acceso:** administradores y desarrolladores integrantes gestionan tareas;
  los clientes asignados consultan solo resúmenes y métricas, sin tareas
  internas ni permisos de modificación.

### Ejecutar las pruebas del hito

Con las dependencias instaladas, desde la carpeta del proyecto:

```powershell
python -m unittest discover -s tests -v
```

Las pruebas usan una base SQLite temporal y una clave generada para la
ejecución; no modifican la base local ni necesitan un archivo `.env`.
Cubren CRUD, asignación, fases, permisos, CSRF, validación de horas,
comparación de tiempos y avance.

### Subir el commit con GitHub Desktop

1. Abre este repositorio en GitHub Desktop. Si no aparece, usa **File > Add local
   repository** y selecciona la carpeta del proyecto que contiene `.git`.
2. En **History**, comprueba que esté el commit del Hito 3.
3. Usa **Fetch origin** para consultar el estado remoto. Si aparecen cambios
   remotos, intégralos y resuelve cualquier conflicto antes de subir.
4. Pulsa **Push origin** para publicar los commits locales.

Crear el commit local no lo publica automáticamente en GitHub.
