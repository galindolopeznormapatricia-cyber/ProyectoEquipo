
import os
import re
from datetime import datetime, timezone
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
    "admin": "Administrador",
    "desarrollador": "Desarrollador",
    "cliente": "Cliente",
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
    total_usuarios = Usuario.query.count() if current_user.rol == "admin" else None
    usuarios_activos = (
        Usuario.query.filter_by(activo=True).count()
        if current_user.rol == "admin" else None
    )
    return render_template(
        "dashboard.html",
        total_usuarios=total_usuarios,
        usuarios_activos=usuarios_activos,
        roles=ROLES,
    )


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
