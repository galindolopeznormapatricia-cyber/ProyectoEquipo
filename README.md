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
