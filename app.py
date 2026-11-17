
import os
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps

import click
from dotenv import load_dotenv
from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, abort
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user,
    logout_user, login_required, current_user
)
from flask_wtf.csrf import CSRFProtect
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from sqlalchemy import inspect
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.exc import IntegrityError

load_dotenv()

app = Flask(__name__, instance_relative_config=True)
os.makedirs(app.instance_path, exist_ok=True)

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
if not app.config["SECRET_KEY"] or len(app.config["SECRET_KEY"]) < 32:
    raise RuntimeError(
        "Configura una SECRET_KEY segura de al menos 32 caracteres en .env"
    )

app.config["SQLALCHEMY_DATABASE_URI"] = (
    "sqlite:///" + os.path.join(app.instance_path, "devproject.db")
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["WTF_CSRF_TIME_LIMIT"] = 3600
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("COOKIE_SECURE", "0") == "1"
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024

db = SQLAlchemy(app)
csrf = CSRFProtect(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Inicia sesión para continuar."
login_manager.login_message_category = "warning"

ROLES = {
    "admin": "Project Manager / Administrador",
    "desarrollador": "Desarrollador / Miembro de equipo",
    "cliente": "Cliente / Stakeholder",
}

ESTADOS_PROYECTO = {
    "planificacion": "Planificación",
    "activo": "Activo",
    "pausado": "Pausado",
    "finalizado": "Finalizado",
}

ESTADOS_TAREA = {
    "pendiente": "Por hacer",
    "en_progreso": "En progreso",
    "en_revision": "En revisión",
    "completada": "Concluida",
}


class Usuario(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    rol = db.Column(db.String(20), nullable=False, default="desarrollador")
    activo = db.Column(db.Boolean, nullable=False, default=True)
    fecha_registro = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    def establecer_password(self, password):
        self.password_hash = generate_password_hash(password)

    def verificar_password(self, password):
        return check_password_hash(self.password_hash, password)


class Proyecto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    descripcion = db.Column(db.Text, nullable=False, default="")
    objetivos = db.Column(db.Text, nullable=False, default="")
    presupuesto = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    estado = db.Column(db.String(20), nullable=False, default="planificacion")
    fecha_inicio = db.Column(db.Date, nullable=True)
    fecha_fin = db.Column(db.Date, nullable=True)
    creado_por_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), nullable=False)
    creado_en = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    creador = db.relationship("Usuario", backref="proyectos_creados")
    miembros = db.relationship(
        "MiembroProyecto",
        back_populates="proyecto",
        cascade="all, delete-orphan",
    )
    fases = db.relationship(
        "Fase",
        back_populates="proyecto",
        cascade="all, delete-orphan",
        order_by="Fase.orden, Fase.id",
    )
    tareas = db.relationship(
        "Tarea",
        back_populates="proyecto",
        cascade="all, delete-orphan",
        order_by="Tarea.id.desc()",
    )


class MiembroProyecto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    proyecto_id = db.Column(
        db.Integer, db.ForeignKey("proyecto.id"), nullable=False
    )
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), nullable=False)
    rol_equipo = db.Column(db.String(80), nullable=False, default="Desarrollo")
    proyecto = db.relationship("Proyecto", back_populates="miembros")
    usuario = db.relationship("Usuario", backref="asignaciones_proyecto")
    __table_args__ = (
        db.UniqueConstraint("proyecto_id", "usuario_id", name="uq_proyecto_miembro"),
    )


class Fase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    proyecto_id = db.Column(db.Integer, db.ForeignKey("proyecto.id"), nullable=False)
    nombre = db.Column(db.String(120), nullable=False)
    descripcion = db.Column(db.Text, nullable=False, default="")
    orden = db.Column(db.Integer, nullable=False, default=0)
    fecha_inicio = db.Column(db.Date, nullable=True)
    fecha_fin = db.Column(db.Date, nullable=True)
    proyecto = db.relationship("Proyecto", back_populates="fases")
    tareas = db.relationship("Tarea", back_populates="fase")


class Tarea(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    proyecto_id = db.Column(
        db.Integer, db.ForeignKey("proyecto.id"), nullable=False
    )
    fase_id = db.Column(db.Integer, db.ForeignKey("fase.id"), nullable=True)
    asignado_a_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), nullable=True)
    titulo = db.Column(db.String(140), nullable=False)
    descripcion = db.Column(db.Text, nullable=False, default="")
    estado = db.Column(db.String(20), nullable=False, default="pendiente")
    prioridad = db.Column(db.String(20), nullable=False, default="normal")
    horas_estimadas = db.Column(db.Numeric(7, 2), nullable=False, default=0)
    fecha_limite = db.Column(db.Date, nullable=True)
    creado_en = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    proyecto = db.relationship("Proyecto", back_populates="tareas")
    fase = db.relationship("Fase", back_populates="tareas")
    asignado_a = db.relationship("Usuario", backref="tareas_asignadas")
    registros_horas = db.relationship(
        "RegistroHoras",
        back_populates="tarea",
        cascade="all, delete-orphan",
        order_by="RegistroHoras.fecha.desc()",
    )


class RegistroHoras(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tarea_id = db.Column(db.Integer, db.ForeignKey("tarea.id"), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), nullable=False)
    horas = db.Column(db.Numeric(5, 2), nullable=False)
    nota = db.Column(db.String(500), nullable=False, default="")
    fecha = db.Column(db.Date, nullable=False, default=date.today)
    tarea = db.relationship("Tarea", back_populates="registros_horas")
    usuario = db.relationship("Usuario", backref="registros_horas")


def actualizar_esquema():
    db.create_all()
    cambios = (
        (
            "proyecto",
            "objetivos",
            "ALTER TABLE proyecto ADD COLUMN objetivos TEXT NOT NULL DEFAULT ''",
        ),
        (
            "miembro_proyecto",
            "rol_equipo",
            "ALTER TABLE miembro_proyecto ADD COLUMN rol_equipo "
            "VARCHAR(80) NOT NULL DEFAULT 'Desarrollo'",
        ),
        ("tarea", "fase_id", "ALTER TABLE tarea ADD COLUMN fase_id INTEGER"),
        (
            "tarea",
            "horas_estimadas",
            "ALTER TABLE tarea ADD COLUMN horas_estimadas "
            "NUMERIC(7, 2) NOT NULL DEFAULT 0",
        ),
    )
    with db.engine.begin() as conexion:
        for tabla, columna, sentencia in cambios:
            columnas = {
                item["name"] for item in inspect(conexion).get_columns(tabla)
            }
            if columna not in columnas:
                conexion.exec_driver_sql(sentencia)
        conexion.exec_driver_sql(
            "UPDATE proyecto SET estado = 'finalizado' WHERE estado = 'completado'"
        )
        conexion.exec_driver_sql(
            "UPDATE tarea SET estado = 'en_revision' "
            "WHERE estado IN ('revision', 'en_revision')"
        )


with app.app_context():
    actualizar_esquema()


@login_manager.user_loader
def cargar_usuario(user_id):
    try:
        return db.session.get(Usuario, int(user_id))
    except (ValueError, TypeError):
        return None


@app.before_request
def verificar_usuario_activo():
    if current_user.is_authenticated and not current_user.activo:
        logout_user()
        flash("Tu cuenta está desactivada. Contacta al administrador.", "danger")
        return redirect(url_for("login"))


def roles_requeridos(*roles):
    def decorador(funcion):
        @wraps(funcion)
        @login_required
        def protegida(*args, **kwargs):
            if current_user.rol not in roles:
                abort(403)
            return funcion(*args, **kwargs)
        return protegida
    return decorador


def validar_password(password):
    if len(password) < 10:
        return "La contraseña debe tener al menos 10 caracteres."
    if not re.search(r"[A-Z]", password):
        return "Incluye al menos una letra mayúscula."
    if not re.search(r"[a-z]", password):
        return "Incluye al menos una letra minúscula."
    if not re.search(r"\d", password):
        return "Incluye al menos un número."
    if not re.search(r"[^A-Za-z0-9]", password):
        return "Incluye al menos un símbolo."
    return None


def normalizar_email(email):
    return email.strip().lower()


def serializer_recuperacion():
    return URLSafeTimedSerializer(
        app.config["SECRET_KEY"], salt="recuperacion-password"
    )


def parsear_fecha(valor, etiqueta):
    if not valor:
        return None, None
    try:
        return date.fromisoformat(valor), None
    except ValueError:
        return None, f"Indica una fecha válida para {etiqueta}."


def proyectos_visibles():
    consulta = Proyecto.query
    if current_user.rol != "admin":
        consulta = consulta.join(MiembroProyecto).filter(
            MiembroProyecto.usuario_id == current_user.id
        )
    return consulta.order_by(Proyecto.creado_en.desc()).all()


def obtener_proyecto_visible(project_id):
    proyecto = db.get_or_404(Proyecto, project_id)
    if current_user.rol != "admin" and not any(
        miembro.usuario_id == current_user.id for miembro in proyecto.miembros
    ):
        abort(403)
    return proyecto


def es_miembro_desarrollador(proyecto, usuario=None):
    usuario = usuario or current_user
    return any(
        miembro.usuario_id == usuario.id
        and miembro.usuario.rol == "desarrollador"
        and miembro.usuario.activo
        for miembro in proyecto.miembros
    )


def horas_de_tarea(tarea):
    return sum(
        (registro.horas for registro in tarea.registros_horas),
        start=Decimal("0"),
    )


def resumen_de_tareas(tareas):
    total = len(tareas)
    completadas = sum(tarea.estado == "completada" for tarea in tareas)
    planificadas = sum(
        (tarea.horas_estimadas for tarea in tareas), start=Decimal("0"),
    )
    reales = sum((horas_de_tarea(tarea) for tarea in tareas), start=Decimal("0"))
    return {
        "total_tareas": total,
        "completadas": completadas,
        "avance": round(completadas * 100 / total) if total else 0,
        "horas_planificadas": planificadas,
        "horas": reales,
        "desviacion": reales - planificadas,
    }


@app.route("/")
def inicio():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/registro", methods=["GET", "POST"])
def registro():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        email = normalizar_email(request.form.get("email", ""))
        password = request.form.get("password", "")
        confirmar = request.form.get("confirmar", "")

        error = None

        if not nombre or len(nombre) > 100:
            error = "Escribe un nombre válido de hasta 100 caracteres."
        elif not email or len(email) > 150 or not re.fullmatch(
            r"[^@\s]+@[^@\s]+\.[^@\s]+", email
        ):
            error = "Escribe un correo electrónico válido."
        elif Usuario.query.filter_by(email=email).first():
            error = "Ese correo ya está registrado."
        elif (error := validar_password(password)):
            pass
        elif password != confirmar:
            error = "Las contraseñas no coinciden."

        if error:
            flash(error, "danger")
        else:
            usuario = Usuario(
                nombre=nombre,
                email=email,
                rol="desarrollador",
                activo=True,
            )
            usuario.establecer_password(password)
            db.session.add(usuario)

            try:
                db.session.commit()
                flash("Cuenta creada. Ya puedes iniciar sesión.", "success")
                return redirect(url_for("login"))
            except IntegrityError:
                db.session.rollback()
                flash("Ese correo ya está registrado.", "danger")

    return render_template("registro.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = normalizar_email(request.form.get("email", ""))
        password = request.form.get("password", "")
        usuario = Usuario.query.filter_by(email=email).first()

        if usuario and usuario.verificar_password(password) and usuario.activo:
            login_user(usuario, remember=False)
            flash("Bienvenido a DevProject Manager.", "success")
            return redirect(url_for("dashboard"))

        flash("Correo o contraseña incorrectos, o cuenta inactiva.", "danger")

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("Has cerrado sesión.", "info")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    proyectos = proyectos_visibles()
    tareas_pendientes = sum(
        1 for proyecto in proyectos
        for tarea in proyecto.tareas
        if tarea.estado != "completada"
    )
    total_usuarios = Usuario.query.count() if current_user.rol == "admin" else None
    usuarios_activos = Usuario.query.filter_by(activo=True).count() if current_user.rol == "admin" else None
    return render_template(
        "dashboard.html",
        proyectos=proyectos[:4],
        total_proyectos=len(proyectos),
        tareas_pendientes=tareas_pendientes,
        total_usuarios=total_usuarios,
        usuarios_activos=usuarios_activos,
        roles=ROLES,
        estados_proyecto=ESTADOS_PROYECTO,
    )


@app.route("/proyectos")
@login_required
def proyectos():
    return render_template(
        "proyectos.html",
        proyectos=proyectos_visibles(),
        estados=ESTADOS_PROYECTO,
    )


@app.route("/proyectos/nuevo", methods=["GET", "POST"])
@roles_requeridos("admin")
def proyecto_nuevo():
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        descripcion = request.form.get("descripcion", "").strip()
        objetivos = request.form.get("objetivos", "").strip()
        estado = request.form.get("estado", "")
        miembros_ids = set(request.form.getlist("miembros", type=int))
        roles_equipo = {
            usuario_id: request.form.get(f"rol_miembro_{usuario_id}", "").strip()
            for usuario_id in miembros_ids
        }

        try:
            presupuesto = Decimal(request.form.get("presupuesto", "0"))
            if (
                not presupuesto.is_finite()
                or presupuesto < 0
                or presupuesto > Decimal("9999999999.99")
            ):
                raise InvalidOperation
        except InvalidOperation:
            presupuesto = Decimal("0")
            error = "El presupuesto debe ser un número válido entre 0 y 9,999,999,999.99."
        else:
            error = None

        fecha_inicio, fecha_error = parsear_fecha(
            request.form.get("fecha_inicio", ""), "de inicio"
        )
        fecha_fin, fin_error = parsear_fecha(
            request.form.get("fecha_fin", ""), "de término"
        )
        usuarios = Usuario.query.filter(
            Usuario.id.in_(miembros_ids),
            Usuario.activo.is_(True),
            Usuario.rol.in_(("desarrollador", "cliente")),
        ).all() if miembros_ids else []

        if not error and (not nombre or len(nombre) > 120):
            error = "El nombre del proyecto es obligatorio y debe tener hasta 120 caracteres."
        elif not error and len(descripcion) > 4000:
            error = "La descripción debe tener hasta 4,000 caracteres."
        elif not error and len(objetivos) > 4000:
            error = "Los objetivos deben tener hasta 4,000 caracteres."
        elif not error and estado not in ESTADOS_PROYECTO:
            error = "Selecciona un estado válido."
        elif not error and any(
            not rol or len(rol) > 80 for rol in roles_equipo.values()
        ):
            error = "Define un rol de equipo de hasta 80 caracteres para cada integrante."
        elif not error and len(usuarios) != len(miembros_ids):
            error = "Solo puedes asignar miembros activos con rol de desarrollador o cliente."
        elif not error and (fecha_error or fin_error):
            error = fecha_error or fin_error
        elif not error and fecha_inicio and fecha_fin and fecha_fin < fecha_inicio:
            error = "La fecha de término no puede ser anterior a la fecha de inicio."

        if error:
            flash(error, "danger")
        else:
            proyecto = Proyecto(
                nombre=nombre,
                descripcion=descripcion,
                objetivos=objetivos,
                presupuesto=presupuesto,
                estado=estado,
                fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin,
                creador=current_user,
                miembros=[
                    MiembroProyecto(
                        usuario=usuario,
                        rol_equipo=roles_equipo[usuario.id],
                    )
                    for usuario in usuarios
                ],
            )
            db.session.add(proyecto)
            db.session.commit()
            flash("Proyecto creado y equipo asignado.", "success")
            return redirect(url_for("proyectos"))

    return render_template(
        "proyecto_form.html",
        proyecto=None,
        estados=ESTADOS_PROYECTO,
        candidatos=Usuario.query.filter(
            Usuario.activo.is_(True),
            Usuario.rol.in_(("desarrollador", "cliente")),
        ).order_by(Usuario.nombre).all(),
        seleccionados=set(),
    )


@app.route("/proyectos/<int:project_id>/editar", methods=["GET", "POST"])
@roles_requeridos("admin")
def proyecto_editar(project_id):
    proyecto = db.get_or_404(Proyecto, project_id)
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        descripcion = request.form.get("descripcion", "").strip()
        objetivos = request.form.get("objetivos", "").strip()
        estado = request.form.get("estado", "")
        miembros_ids = set(request.form.getlist("miembros", type=int))
        roles_equipo = {
            usuario_id: request.form.get(f"rol_miembro_{usuario_id}", "").strip()
            for usuario_id in miembros_ids
        }

        try:
            presupuesto = Decimal(request.form.get("presupuesto", "0"))
            if (
                not presupuesto.is_finite()
                or presupuesto < 0
                or presupuesto > Decimal("9999999999.99")
            ):
                raise InvalidOperation
        except InvalidOperation:
            presupuesto = proyecto.presupuesto
            error = "El presupuesto debe ser un número válido entre 0 y 9,999,999,999.99."
        else:
            error = None

        fecha_inicio, fecha_error = parsear_fecha(
            request.form.get("fecha_inicio", ""), "de inicio"
        )
        fecha_fin, fin_error = parsear_fecha(
            request.form.get("fecha_fin", ""), "de término"
        )
        usuarios = Usuario.query.filter(
            Usuario.id.in_(miembros_ids),
            Usuario.activo.is_(True),
            Usuario.rol.in_(("desarrollador", "cliente")),
        ).all() if miembros_ids else []

        if not error and (not nombre or len(nombre) > 120):
            error = "El nombre del proyecto es obligatorio y debe tener hasta 120 caracteres."
        elif not error and len(descripcion) > 4000:
            error = "La descripción debe tener hasta 4,000 caracteres."
        elif not error and len(objetivos) > 4000:
            error = "Los objetivos deben tener hasta 4,000 caracteres."
        elif not error and estado not in ESTADOS_PROYECTO:
            error = "Selecciona un estado válido."
        elif not error and any(
            not rol or len(rol) > 80 for rol in roles_equipo.values()
        ):
            error = "Define un rol de equipo de hasta 80 caracteres para cada integrante."
        elif not error and len(usuarios) != len(miembros_ids):
            error = "Solo puedes asignar miembros activos con rol de desarrollador o cliente."
        elif not error and (fecha_error or fin_error):
            error = fecha_error or fin_error
        elif not error and fecha_inicio and fecha_fin and fecha_fin < fecha_inicio:
            error = "La fecha de término no puede ser anterior a la fecha de inicio."

        if error:
            flash(error, "danger")
        else:
            proyecto.nombre = nombre
            proyecto.descripcion = descripcion
            proyecto.objetivos = objetivos
            proyecto.presupuesto = presupuesto
            proyecto.estado = estado
            proyecto.fecha_inicio = fecha_inicio
            proyecto.fecha_fin = fecha_fin
            nuevos_miembros = {usuario.id: usuario for usuario in usuarios}
            miembro_actual_ids = {
                miembro.usuario_id for miembro in proyecto.miembros
            }
            for miembro in list(proyecto.miembros):
                if miembro.usuario_id not in nuevos_miembros:
                    proyecto.miembros.remove(miembro)
            for usuario in usuarios:
                if usuario.id not in miembro_actual_ids:
                    proyecto.miembros.append(
                        MiembroProyecto(
                            usuario=usuario,
                            rol_equipo=roles_equipo[usuario.id],
                        )
                    )
                else:
                    asignacion = next(
                        miembro for miembro in proyecto.miembros
                        if miembro.usuario_id == usuario.id
                    )
                    asignacion.rol_equipo = roles_equipo[usuario.id]
            desarrollador_ids = {
                usuario.id for usuario in usuarios
                if usuario.rol == "desarrollador"
            }
            for tarea in proyecto.tareas:
                if (
                    tarea.asignado_a_id
                    and tarea.asignado_a_id not in desarrollador_ids
                ):
                    tarea.asignado_a = None
            db.session.commit()
            flash("Proyecto actualizado correctamente.", "success")
            return redirect(url_for("proyecto_detalle", project_id=proyecto.id))

    return render_template(
        "proyecto_form.html",
        proyecto=proyecto,
        estados=ESTADOS_PROYECTO,
        candidatos=Usuario.query.filter(
            Usuario.activo.is_(True),
            Usuario.rol.in_(("desarrollador", "cliente")),
        ).order_by(Usuario.nombre).all(),
        seleccionados={miembro.usuario_id for miembro in proyecto.miembros},
    )


@app.route("/proyectos/<int:project_id>/eliminar", methods=["POST"])
@roles_requeridos("admin")
def proyecto_eliminar(project_id):
    proyecto = db.get_or_404(Proyecto, project_id)
    db.session.delete(proyecto)
    db.session.commit()
    flash("Proyecto eliminado.", "info")
    return redirect(url_for("proyectos"))


@app.route("/proyectos/<int:project_id>")
@login_required
def proyecto_detalle(project_id):
    proyecto = obtener_proyecto_visible(project_id)
    puede_trabajar = current_user.rol == "admin" or (
        current_user.rol == "desarrollador"
        and es_miembro_desarrollador(proyecto)
    )
    return render_template(
        "proyecto_detalle.html",
        proyecto=proyecto,
        estados_tarea=ESTADOS_TAREA,
        puede_trabajar=puede_trabajar,
        es_admin=current_user.rol == "admin",
        horas_de_tarea=horas_de_tarea,
        resumen=resumen_de_tareas(proyecto.tareas),
        resumen_de_tareas=resumen_de_tareas,
    )


@app.route("/proyectos/<int:project_id>/fases/nueva", methods=["GET", "POST"])
@roles_requeridos("admin")
def fase_nueva(project_id):
    proyecto = db.get_or_404(Proyecto, project_id)
    return guardar_fase(proyecto)


@app.route("/fases/<int:phase_id>/editar", methods=["GET", "POST"])
@roles_requeridos("admin")
def fase_editar(phase_id):
    fase = db.get_or_404(Fase, phase_id)
    return guardar_fase(fase.proyecto, fase)


def guardar_fase(proyecto, fase=None):
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        descripcion = request.form.get("descripcion", "").strip()
        fecha_inicio, fecha_error = parsear_fecha(
            request.form.get("fecha_inicio", ""), "de inicio"
        )
        fecha_fin, fin_error = parsear_fecha(
            request.form.get("fecha_fin", ""), "de término"
        )
        try:
            orden = int(request.form.get("orden", "0"))
            error = None
        except ValueError:
            orden = 0
            error = "El orden debe ser un número entero."

        if not error and (not nombre or len(nombre) > 120):
            error = "El nombre de la fase es obligatorio y debe tener hasta 120 caracteres."
        elif not error and len(descripcion) > 2000:
            error = "La descripción debe tener hasta 2,000 caracteres."
        elif not error and (fecha_error or fin_error):
            error = fecha_error or fin_error
        elif not error and fecha_inicio and fecha_fin and fecha_fin < fecha_inicio:
            error = "La fecha de término no puede ser anterior a la fecha de inicio."

        if error:
            flash(error, "danger")
        else:
            if fase is None:
                fase = Fase(proyecto=proyecto)
                db.session.add(fase)
            fase.nombre = nombre
            fase.descripcion = descripcion
            fase.orden = orden
            fase.fecha_inicio = fecha_inicio
            fase.fecha_fin = fecha_fin
            db.session.commit()
            flash("Fase guardada correctamente.", "success")
            return redirect(url_for("proyecto_detalle", project_id=proyecto.id))

    return render_template("fase_form.html", proyecto=proyecto, fase=fase)


@app.route("/fases/<int:phase_id>/eliminar", methods=["POST"])
@roles_requeridos("admin")
def fase_eliminar(phase_id):
    fase = db.get_or_404(Fase, phase_id)
    proyecto_id = fase.proyecto_id
    for tarea in fase.tareas:
        tarea.fase = None
    db.session.delete(fase)
    db.session.commit()
    flash("Fase eliminada. Las tareas relacionadas siguen en el proyecto.", "info")
    return redirect(url_for("proyecto_detalle", project_id=proyecto_id))


@app.route("/proyectos/<int:project_id>/tareas/nueva", methods=["GET", "POST"])
@roles_requeridos("admin", "desarrollador")
def tarea_nueva(project_id):
    proyecto = obtener_proyecto_visible(project_id)
    if current_user.rol == "desarrollador" and not es_miembro_desarrollador(proyecto):
        abort(403)

    return guardar_tarea(proyecto)


@app.route("/tareas/<int:task_id>/editar", methods=["GET", "POST"])
@roles_requeridos("admin", "desarrollador")
def tarea_editar(task_id):
    tarea = db.get_or_404(Tarea, task_id)
    proyecto = obtener_proyecto_visible(tarea.proyecto_id)
    if current_user.rol == "desarrollador" and not es_miembro_desarrollador(proyecto):
        abort(403)
    return guardar_tarea(proyecto, tarea)


def guardar_tarea(proyecto, tarea=None):
    desarrolladores = [
        miembro.usuario
        for miembro in proyecto.miembros
        if miembro.usuario.rol == "desarrollador" and miembro.usuario.activo
    ]
    if request.method == "POST":
        titulo = request.form.get("titulo", "").strip()
        descripcion = request.form.get("descripcion", "").strip()
        estado = request.form.get("estado", "pendiente")
        prioridad = request.form.get("prioridad", "normal")
        asignado_raw = request.form.get("asignado_a_id", "")
        fase_raw = request.form.get("fase_id", "")
        fecha_limite, fecha_error = parsear_fecha(
            request.form.get("fecha_limite", ""), "de entrega"
        )
        fase = next(
            (fase for fase in proyecto.fases if str(fase.id) == fase_raw),
            None,
        ) if fase_raw else None
        asignado = next(
            (usuario for usuario in desarrolladores
             if str(usuario.id) == asignado_raw),
            None,
        ) if asignado_raw else None
        try:
            horas_estimadas = Decimal(request.form.get("horas_estimadas", "0"))
            if (
                not horas_estimadas.is_finite()
                or horas_estimadas < 0
                or horas_estimadas > Decimal("99999.99")
                or horas_estimadas != horas_estimadas.quantize(Decimal("0.01"))
            ):
                raise InvalidOperation
            error = None
        except InvalidOperation:
            horas_estimadas = Decimal("0")
            error = (
                "Las horas estimadas deben ser un número entre 0 y 99,999.99 "
                "con un máximo de dos decimales."
            )

        if not error and (not titulo or len(titulo) > 140):
            error = "El título es obligatorio y debe tener hasta 140 caracteres."
        elif not error and estado not in ESTADOS_TAREA:
            error = "Selecciona un estado válido."
        elif not error and prioridad not in ("baja", "normal", "alta"):
            error = "Selecciona una prioridad válida."
        elif not error and asignado_raw and not asignado:
            error = "La persona asignada debe ser un desarrollador activo del proyecto."
        elif not error and fase_raw and not fase:
            error = "La fase seleccionada debe pertenecer a este proyecto."
        elif not error and len(descripcion) > 4000:
            error = "La descripción debe tener hasta 4,000 caracteres."
        elif not error and fecha_error:
            error = fecha_error

        if error:
            flash(error, "danger")
        else:
            if tarea is None:
                tarea = Tarea(proyecto=proyecto)
                db.session.add(tarea)
            tarea.titulo = titulo
            tarea.descripcion = descripcion
            tarea.estado = estado
            tarea.prioridad = prioridad
            tarea.horas_estimadas = horas_estimadas
            tarea.fecha_limite = fecha_limite
            tarea.fase = fase
            tarea.asignado_a = asignado
            db.session.commit()
            flash("Tarea guardada correctamente.", "success")
            return redirect(url_for("proyecto_detalle", project_id=proyecto.id))

    return render_template(
        "tarea_form.html",
        proyecto=proyecto,
        tarea=tarea,
        estados=ESTADOS_TAREA,
        desarrolladores=desarrolladores,
        fases=proyecto.fases,
    )


@app.route("/tareas/<int:task_id>/eliminar", methods=["POST"])
@roles_requeridos("admin", "desarrollador")
def tarea_eliminar(task_id):
    tarea = db.get_or_404(Tarea, task_id)
    proyecto = obtener_proyecto_visible(tarea.proyecto_id)
    if current_user.rol == "desarrollador" and not es_miembro_desarrollador(proyecto):
        abort(403)
    db.session.delete(tarea)
    db.session.commit()
    flash("Tarea eliminada.", "info")
    return redirect(url_for("proyecto_detalle", project_id=proyecto.id))


@app.route("/tareas/<int:task_id>/horas", methods=["POST"])
@roles_requeridos("desarrollador")
def registrar_horas(task_id):
    tarea = db.get_or_404(Tarea, task_id)
    proyecto = obtener_proyecto_visible(tarea.proyecto_id)
    if not es_miembro_desarrollador(proyecto):
        abort(403)
    if tarea.estado == "completada":
        flash("No se pueden registrar horas en una tarea completada.", "danger")
        return redirect(url_for("proyecto_detalle", project_id=proyecto.id))
    if tarea.asignado_a_id not in (None, current_user.id):
        flash("Solo puedes reportar horas en tareas sin asignar o asignadas a ti.", "danger")
        return redirect(url_for("proyecto_detalle", project_id=proyecto.id))

    try:
        horas = Decimal(request.form.get("horas", ""))
        if (
            not horas.is_finite()
            or horas <= 0
            or horas > 24
            or horas != horas.quantize(Decimal("0.01"))
        ):
            raise InvalidOperation
    except InvalidOperation:
        flash(
            "Las horas deben ser un número mayor a 0 y no mayor a 24 "
            "con un máximo de dos decimales.",
            "danger",
        )
        return redirect(url_for("proyecto_detalle", project_id=proyecto.id))

    fecha, error = parsear_fecha(request.form.get("fecha", ""), "del reporte")
    nota = request.form.get("nota", "").strip()
    if error or len(nota) > 500:
        flash(error or "La descripción debe tener hasta 500 caracteres.", "danger")
    else:
        db.session.add(
            RegistroHoras(
                tarea=tarea,
                usuario=current_user,
                horas=horas,
                fecha=fecha or date.today(),
                nota=nota,
            )
        )
        db.session.commit()
        flash("Horas registradas correctamente.", "success")
    return redirect(url_for("proyecto_detalle", project_id=proyecto.id))


@app.route("/informes")
@login_required
def informes():
    resumenes = []
    for proyecto in proyectos_visibles():
        resumenes.append(
            {
                "proyecto": proyecto,
                **resumen_de_tareas(proyecto.tareas),
            }
        )
    return render_template("informes.html", resumenes=resumenes)


@app.route("/usuarios")
@roles_requeridos("admin")
def usuarios():
    lista = Usuario.query.order_by(Usuario.id.desc()).all()
    return render_template("usuarios.html", usuarios=lista, roles=ROLES)


@app.route("/usuarios/nuevo", methods=["GET", "POST"])
@roles_requeridos("admin")
def usuario_nuevo():
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        email = normalizar_email(request.form.get("email", ""))
        password = request.form.get("password", "")
        rol = request.form.get("rol", "")
        activo = request.form.get("activo") == "1"

        error = None
        if not nombre or len(nombre) > 100:
            error = "Escribe un nombre válido."
        elif not email or len(email) > 150 or not re.fullmatch(
            r"[^@\s]+@[^@\s]+\.[^@\s]+", email
        ):
            error = "Escribe un correo válido."
        elif Usuario.query.filter_by(email=email).first():
            error = "Ese correo ya está registrado."
        elif rol not in ROLES:
            error = "Selecciona un rol válido."
        else:
            error = validar_password(password)

        if error:
            flash(error, "danger")
        else:
            usuario = Usuario(
                nombre=nombre, email=email, rol=rol, activo=activo
            )
            usuario.establecer_password(password)
            db.session.add(usuario)

            try:
                db.session.commit()
                flash("Usuario creado correctamente.", "success")
                return redirect(url_for("usuarios"))
            except IntegrityError:
                db.session.rollback()
                flash("No se pudo crear el usuario. Verifica el correo.", "danger")

    return render_template("usuario_form.html", usuario=None, roles=ROLES)


@app.route("/usuarios/<int:user_id>/editar", methods=["GET", "POST"])
@roles_requeridos("admin")
def usuario_editar(user_id):
    usuario = db.get_or_404(Usuario, user_id)

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        email = normalizar_email(request.form.get("email", ""))
        rol = request.form.get("rol", "")
        password = request.form.get("password", "")
        activo = request.form.get("activo") == "1"

        error = None
        existente = Usuario.query.filter_by(email=email).first()

        if not nombre or len(nombre) > 100:
            error = "Escribe un nombre válido."
        elif not email or len(email) > 150 or not re.fullmatch(
            r"[^@\s]+@[^@\s]+\.[^@\s]+", email
        ):
            error = "Escribe un correo válido."
        elif existente and existente.id != usuario.id:
            error = "Ese correo ya pertenece a otro usuario."
        elif rol not in ROLES:
            error = "Selecciona un rol válido."
        elif password:
            error = validar_password(password)

        if not error and usuario.id == current_user.id:
            if not activo:
                error = "No puedes desactivar tu propia cuenta."
            elif rol != "admin":
                error = "No puedes quitarte el rol de administrador."

        if error:
            flash(error, "danger")
        else:
            usuario.nombre = nombre
            usuario.email = email
            usuario.rol = rol
            usuario.activo = activo

            if rol != "desarrollador" or not activo:
                for tarea in usuario.tareas_asignadas:
                    tarea.asignado_a = None

            if password:
                usuario.establecer_password(password)

            try:
                db.session.commit()
                flash("Usuario actualizado correctamente.", "success")
                return redirect(url_for("usuarios"))
            except IntegrityError:
                db.session.rollback()
                flash("No se pudo actualizar el usuario.", "danger")

    return render_template("usuario_form.html", usuario=usuario, roles=ROLES)


@app.route("/usuarios/<int:user_id>/estado", methods=["POST"])
@roles_requeridos("admin")
def usuario_estado(user_id):
    usuario = db.get_or_404(Usuario, user_id)

    if usuario.id == current_user.id:
        flash("No puedes desactivar tu propia cuenta.", "danger")
    else:
        usuario.activo = not usuario.activo
        if not usuario.activo:
            for tarea in usuario.tareas_asignadas:
                tarea.asignado_a = None
        db.session.commit()
        flash("Estado del usuario actualizado.", "success")

    return redirect(url_for("usuarios"))


@app.route("/recuperar", methods=["GET", "POST"])
def recuperar():
    if request.method == "POST":
        email = normalizar_email(request.form.get("email", ""))
        usuario = Usuario.query.filter_by(email=email, activo=True).first()

        # En producción, este enlace debe enviarse por correo.
        # Para las pruebas locales se muestra en la terminal.
        if usuario:
            token = serializer_recuperacion().dumps(usuario.email)
            enlace = url_for("restablecer", token=token, _external=True)
            app.logger.warning("ENLACE LOCAL DE RECUPERACIÓN: %s", enlace)
            flash(
                "Si la cuenta existe y está activa, se generó una solicitud. "
                "En modo local revisa la terminal de Flask.",
                "info",
            )
        else:
            flash(
                "Si la cuenta existe y está activa, se generó una solicitud.",
                "info",
            )

        return redirect(url_for("login"))

    return render_template("recuperar.html")


@app.route("/restablecer/<token>", methods=["GET", "POST"])
def restablecer(token):
    try:
        email = serializer_recuperacion().loads(token, max_age=900)
    except SignatureExpired:
        flash("El enlace expiró. Solicita uno nuevo.", "danger")
        return redirect(url_for("recuperar"))
    except BadSignature:
        flash("El enlace no es válido.", "danger")
        return redirect(url_for("recuperar"))

    usuario = Usuario.query.filter_by(email=email, activo=True).first()
    if not usuario:
        flash("La cuenta no existe o está inactiva.", "danger")
        return redirect(url_for("recuperar"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirmar = request.form.get("confirmar", "")
        error = validar_password(password)

        if error:
            flash(error, "danger")
        elif password != confirmar:
            flash("Las contraseñas no coinciden.", "danger")
        else:
            usuario.establecer_password(password)
            db.session.commit()
            flash("Contraseña actualizada. Ya puedes iniciar sesión.", "success")
            return redirect(url_for("login"))

    return render_template("restablecer.html")


@app.cli.command("init-db")
def init_db():
    """Crea las tablas de la base de datos."""
    db.create_all()
    click.echo("Base de datos inicializada correctamente.")


@app.cli.command("seed-admin")
def seed_admin():
    """Crea el administrador inicial usando variables de entorno."""
    email = normalizar_email(os.getenv("ADMIN_EMAIL", ""))
    password = os.getenv("ADMIN_PASSWORD", "")
    nombre = os.getenv("ADMIN_NAME", "Administrador")

    if not email or not password:
        raise click.ClickException(
            "Define ADMIN_EMAIL y ADMIN_PASSWORD en el archivo .env."
        )

    error = validar_password(password)
    if error:
        raise click.ClickException(error)

    if Usuario.query.filter_by(email=email).first():
        click.echo("El usuario administrador ya existe.")
        return

    admin = Usuario(
        nombre=nombre,
        email=email,
        rol="admin",
        activo=True,
    )
    admin.establecer_password(password)
    db.session.add(admin)
    db.session.commit()
    click.echo("Administrador creado correctamente.")


@app.cli.command("restaurar-admin")
@click.argument("email_objetivo", required=False)
def restaurar_admin(email_objetivo=None):
    """Restablece el administrador del archivo .env o del correo indicado."""
    email_indicado = normalizar_email(email_objetivo) if email_objetivo else ""
    email = email_indicado or normalizar_email(os.getenv("ADMIN_EMAIL", ""))
    password = os.getenv("ADMIN_PASSWORD", "")
    nombre = os.getenv("ADMIN_NAME", "Administrador")

    if not email:
        raise click.ClickException(
            "Define ADMIN_EMAIL en .env o indica el correo del administrador."
        )

    usuario = Usuario.query.filter_by(email=email).first()
    if usuario and usuario.rol != "admin":
        raise click.ClickException(
            "El correo indicado pertenece a una cuenta que no tiene rol de administrador."
        )
    if email_indicado and not usuario:
        raise click.ClickException(
            "No existe una cuenta administradora con ese correo. "
            "Revisa el correo e inténtalo de nuevo."
        )

    error = validar_password(password) if not email_indicado else "prompt"
    if error:
        password = click.prompt(
            "Nueva contraseña segura para el administrador",
            hide_input=True,
            confirmation_prompt=True,
        )
        error = validar_password(password)
    if error:
        raise click.ClickException(error)

    if not usuario:
        usuario = Usuario(nombre=nombre, email=email, rol="admin")
        db.session.add(usuario)

    usuario.nombre = nombre
    usuario.activo = True
    usuario.establecer_password(password)
    db.session.commit()
    click.echo(
        f"Acceso de administrador restablecido para {email}. "
        "Inicia sesión con esa cuenta y la contraseña nueva."
    )


@app.cli.command("crear-tablas")
def crear_tablas():
    """Alias para inicializar las tablas."""
    db.create_all()
    click.echo("Tablas creadas.")


@app.errorhandler(403)
def prohibido(error):
    return render_template(
        "base.html",
        error_titulo="Acceso denegado",
        error_mensaje="No tienes permisos para acceder a esta sección.",
    ), 403


@app.errorhandler(413)
def archivo_grande(error):
    return "La solicitud supera el límite permitido de 2 MB.", 413


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1")
