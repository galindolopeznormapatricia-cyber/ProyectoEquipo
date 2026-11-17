import importlib
import secrets
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from flask import Flask, g


class Hito3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directorio = tempfile.TemporaryDirectory()

        def crear_app(*args, **kwargs):
            kwargs["instance_path"] = cls.directorio.name
            return Flask(*args, **kwargs)

        with patch.dict("os.environ", {"SECRET_KEY": secrets.token_hex(32)}):
            with patch("flask.Flask", side_effect=crear_app):
                cls.modulo = importlib.import_module("app")
        cls.app = cls.modulo.app
        cls.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            cls.modulo.db.session.remove()
            cls.modulo.db.engine.dispose()
        cls.directorio.cleanup()

    def setUp(self):
        self.contexto = self.app.app_context()
        self.contexto.push()
        self.addCleanup(self.contexto.pop)
        self.db = self.modulo.db
        self.db.drop_all()
        self.db.create_all()
        self.addCleanup(self.db.session.remove)
        self.cliente = self.app.test_client()
        self.admin = self.modulo.Usuario(
            nombre="Manager", email="manager@example.test",
            password_hash="no-login", rol="admin",
        )
        self.dev = self.modulo.Usuario(
            nombre="Desarrollo", email="dev@example.test",
            password_hash="no-login", rol="desarrollador",
        )
        self.otro = self.modulo.Usuario(
            nombre="Externo", email="otro@example.test",
            password_hash="no-login", rol="desarrollador",
        )
        self.lector = self.modulo.Usuario(
            nombre="Cliente", email="cliente@example.test",
            password_hash="no-login", rol="cliente",
        )
        self.proyecto = self.modulo.Proyecto(
            nombre="Proyecto Hito 3", creador=self.admin,
        )
        self.proyecto.miembros = [
            self.modulo.MiembroProyecto(usuario=self.dev),
            self.modulo.MiembroProyecto(usuario=self.lector),
        ]
        self.fase = self.modulo.Fase(nombre="Implementacion", proyecto=self.proyecto)
        self.proyecto_externo = self.modulo.Proyecto(
            nombre="Otro proyecto", creador=self.admin,
        )
        self.fase_externa = self.modulo.Fase(
            nombre="Fase externa", proyecto=self.proyecto_externo,
        )
        self.db.session.add_all([
            self.proyecto, self.proyecto_externo, self.otro,
        ])
        self.db.session.commit()
        self.entrar(self.admin)

    def entrar(self, usuario):
        g.pop("_login_user", None)
        with self.cliente.session_transaction() as sesion:
            sesion.clear()
            sesion["_user_id"] = str(usuario.id)
            sesion["_fresh"] = True

    def datos_tarea(self, **cambios):
        datos = {
            "titulo": "Implementar modulo",
            "descripcion": "Gestion de tareas",
            "estado": "pendiente",
            "prioridad": "alta",
            "horas_estimadas": "8.00",
            "asignado_a_id": str(self.dev.id),
            "fase_id": str(self.fase.id),
        }
        datos.update(cambios)
        return datos

    def crear_tarea(self, **cambios):
        respuesta = self.cliente.post(
            f"/proyectos/{self.proyecto.id}/tareas/nueva",
            data=self.datos_tarea(**cambios),
        )
        self.assertEqual(respuesta.status_code, 302)
        return self.modulo.Tarea.query.order_by(self.modulo.Tarea.id.desc()).first()

    def test_crud_asignacion_fase_y_eliminacion_de_horas(self):
        tarea = self.crear_tarea()
        self.assertEqual(tarea.asignado_a_id, self.dev.id)
        self.assertEqual(tarea.fase_id, self.fase.id)
        self.assertEqual(tarea.horas_estimadas, Decimal("8.00"))
        detalle = self.cliente.get(f"/proyectos/{self.proyecto.id}")
        self.assertEqual(detalle.status_code, 200)
        self.assertIn(b"Implementar modulo", detalle.data)
        respuesta = self.cliente.post(
            f"/tareas/{tarea.id}/editar",
            data=self.datos_tarea(
                titulo="Modulo actualizado", estado="en_progreso",
                horas_estimadas="10.50",
            ),
        )
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(tarea.titulo, "Modulo actualizado")
        self.assertEqual(tarea.estado, "en_progreso")
        self.assertEqual(tarea.horas_estimadas, Decimal("10.50"))
        self.entrar(self.dev)
        respuesta = self.cliente.post(
            f"/tareas/{tarea.id}/horas",
            data={"horas": "2.50", "fecha": "2026-11-16", "nota": "Avance"},
        )
        self.assertEqual(respuesta.status_code, 302)
        registro = self.modulo.RegistroHoras.query.one()
        self.assertEqual(registro.horas, Decimal("2.50"))
        self.assertEqual(registro.fecha, date(2026, 11, 16))
        self.assertEqual(registro.usuario_id, self.dev.id)
        self.assertEqual(registro.nota, "Avance")
        respuesta = self.cliente.post(f"/tareas/{tarea.id}/eliminar")
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(self.modulo.Tarea.query.count(), 0)
        self.assertEqual(self.modulo.RegistroHoras.query.count(), 0)

    def test_rechaza_responsables_y_fases_de_otro_proyecto(self):
        for cambios in (
            {"asignado_a_id": str(self.otro.id)},
            {"asignado_a_id": str(self.lector.id)},
            {"fase_id": str(self.fase_externa.id)},
        ):
            with self.subTest(cambios=cambios):
                respuesta = self.cliente.post(
                    f"/proyectos/{self.proyecto.id}/tareas/nueva",
                    data=self.datos_tarea(**cambios),
                )
                self.assertEqual(respuesta.status_code, 200)
                self.assertEqual(self.modulo.Tarea.query.count(), 0)
        self.dev.activo = False
        self.db.session.commit()
        respuesta = self.cliente.post(
            f"/proyectos/{self.proyecto.id}/tareas/nueva",
            data=self.datos_tarea(),
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(self.modulo.Tarea.query.count(), 0)

    def test_rechaza_estimaciones_invalidas_sin_redondearlas(self):
        for horas in ("-1", "100000", "NaN", "Infinity", "", "abc", "0.001"):
            with self.subTest(horas=horas):
                respuesta = self.cliente.post(
                    f"/proyectos/{self.proyecto.id}/tareas/nueva",
                    data=self.datos_tarea(horas_estimadas=horas),
                )
                self.assertEqual(respuesta.status_code, 200)
                self.assertEqual(self.modulo.Tarea.query.count(), 0)

    def test_rechaza_reportes_invalidos_sin_redondearlos(self):
        tarea = self.crear_tarea()
        self.entrar(self.dev)
        for horas in ("0", "-1", "24.01", "NaN", "Infinity", "", "abc", "0.001"):
            with self.subTest(horas=horas):
                respuesta = self.cliente.post(
                    f"/tareas/{tarea.id}/horas", data={"horas": horas},
                )
                self.assertEqual(respuesta.status_code, 302)
                self.assertEqual(self.modulo.RegistroHoras.query.count(), 0)
        for datos in (
            {"horas": "1", "fecha": "invalida"},
            {"horas": "1", "nota": "x" * 501},
        ):
            self.cliente.post(f"/tareas/{tarea.id}/horas", data=datos)
            self.assertEqual(self.modulo.RegistroHoras.query.count(), 0)

    def test_limites_validos_y_tarea_sin_asignar_ni_fase(self):
        for horas in ("0", "99999.99"):
            with self.subTest(horas=horas):
                tarea = self.crear_tarea(
                    horas_estimadas=horas, asignado_a_id="", fase_id="",
                )
                self.assertEqual(tarea.horas_estimadas, Decimal(horas))
                self.assertIsNone(tarea.asignado_a_id)
                self.assertIsNone(tarea.fase_id)
        self.entrar(self.dev)
        for horas in ("0.01", "24"):
            self.cliente.post(f"/tareas/{tarea.id}/horas", data={"horas": horas})
        self.assertEqual(self.modulo.RegistroHoras.query.count(), 2)
        self.assertEqual(self.modulo.horas_de_tarea(tarea), Decimal("24.01"))

    def test_edicion_invalida_conserva_tarea_y_registros(self):
        tarea = self.crear_tarea()
        self.db.session.add(self.modulo.RegistroHoras(
            tarea=tarea, usuario=self.dev, horas=Decimal("3"),
        ))
        self.db.session.commit()
        for cambios in (
            {"estado": "desconocido"}, {"prioridad": "urgente"},
            {"titulo": ""}, {"fecha_limite": "invalida"},
            {"horas_estimadas": "NaN"}, {"fase_id": str(self.fase_externa.id)},
        ):
            with self.subTest(cambios=cambios):
                respuesta = self.cliente.post(
                    f"/tareas/{tarea.id}/editar",
                    data=self.datos_tarea(**cambios),
                )
                self.assertEqual(respuesta.status_code, 200)
                self.assertEqual(tarea.titulo, "Implementar modulo")
                self.assertEqual(tarea.estado, "pendiente")
                self.assertEqual(tarea.horas_estimadas, Decimal("8"))
                self.assertEqual(tarea.fase_id, self.fase.id)
                self.assertEqual(self.modulo.horas_de_tarea(tarea), Decimal("3"))

    def test_eliminar_fase_conserva_tareas_y_horas(self):
        tarea = self.crear_tarea()
        self.db.session.add(self.modulo.RegistroHoras(
            tarea=tarea, usuario=self.dev, horas=Decimal("3"),
        ))
        self.db.session.commit()
        respuesta = self.cliente.post(f"/fases/{self.fase.id}/eliminar")
        self.assertEqual(respuesta.status_code, 302)
        self.db.session.expire_all()
        self.assertIsNone(tarea.fase_id)
        self.assertEqual(self.modulo.Tarea.query.count(), 1)
        self.assertEqual(self.modulo.horas_de_tarea(tarea), Decimal("3"))

    def test_permisos_de_tareas_y_reportes(self):
        tarea = self.crear_tarea()
        for usuario in (self.otro, self.lector):
            self.entrar(usuario)
            for ruta in (
                f"/proyectos/{self.proyecto.id}/tareas/nueva",
                f"/tareas/{tarea.id}/editar",
                f"/tareas/{tarea.id}/eliminar",
                f"/tareas/{tarea.id}/horas",
            ):
                with self.subTest(usuario=usuario.rol, ruta=ruta):
                    self.assertEqual(self.cliente.post(ruta).status_code, 403)
        self.assertEqual(self.modulo.Tarea.query.count(), 1)
        self.assertEqual(self.modulo.RegistroHoras.query.count(), 0)
        self.entrar(self.dev)
        tarea.asignado_a = self.otro
        self.db.session.commit()
        self.cliente.post(f"/tareas/{tarea.id}/horas", data={"horas": "1"})
        self.assertEqual(self.modulo.RegistroHoras.query.count(), 0)
        tarea.asignado_a = self.dev
        tarea.estado = "completada"
        self.db.session.commit()
        self.cliente.post(f"/tareas/{tarea.id}/horas", data={"horas": "1"})
        self.assertEqual(self.modulo.RegistroHoras.query.count(), 0)
        detalle = self.cliente.get(f"/proyectos/{self.proyecto.id}")
        self.assertNotIn(
            f'action="/tareas/{tarea.id}/horas"'.encode(), detalle.data,
        )

    def test_resumen_compara_horas_y_avance_sin_filtros(self):
        tarea = self.crear_tarea(horas_estimadas="8.25", estado="completada")
        self.db.session.add(self.modulo.Tarea(
            proyecto=self.proyecto, titulo="Sin fase", horas_estimadas=Decimal("2"),
        ))
        self.db.session.add(self.modulo.RegistroHoras(
            tarea=tarea, usuario=self.dev, horas=Decimal("12.50"),
        ))
        self.db.session.commit()
        resumen = self.modulo.resumen_de_tareas(self.proyecto.tareas)
        self.assertEqual(resumen["total_tareas"], 2)
        self.assertEqual(resumen["completadas"], 1)
        self.assertEqual(resumen["avance"], 50)
        self.assertEqual(resumen["horas_planificadas"], Decimal("10.25"))
        self.assertEqual(resumen["horas"], Decimal("12.50"))
        self.assertEqual(resumen["desviacion"], Decimal("2.25"))
        fase = self.modulo.resumen_de_tareas(self.fase.tareas)
        self.assertEqual(fase["avance"], 100)
        self.assertEqual(fase["desviacion"], Decimal("4.25"))
        for ruta in (f"/proyectos/{self.proyecto.id}", "/informes"):
            respuesta = self.cliente.get(ruta)
            self.assertEqual(respuesta.status_code, 200)
            texto = respuesta.get_data(as_text=True)
            self.assertIn("Horas planificadas", texto)
            self.assertIn("10.25", texto)
            self.assertIn("12.50", texto)
            self.assertIn("+2.25", texto)
            self.assertIn("50%", texto)

    def test_proyecto_vacio_y_clientes_solo_ven_su_resumen(self):
        resumen = self.modulo.resumen_de_tareas([])
        self.assertEqual(resumen["avance"], 0)
        self.assertEqual(resumen["horas_planificadas"], Decimal("0"))
        self.assertEqual(resumen["horas"], Decimal("0"))
        self.assertEqual(resumen["desviacion"], Decimal("0"))
        self.crear_tarea(titulo="Tarea interna confidencial")
        self.entrar(self.lector)
        for ruta in (f"/proyectos/{self.proyecto.id}", "/informes"):
            respuesta = self.cliente.get(ruta)
            self.assertEqual(respuesta.status_code, 200)
            self.assertNotIn(b"Tarea interna confidencial", respuesta.data)
            self.assertNotIn(b"Otro proyecto", respuesta.data)
        self.assertEqual(
            self.cliente.get(f"/proyectos/{self.proyecto_externo.id}").status_code,
            403,
        )

    def test_desviacion_negativa_y_sin_estimacion(self):
        tarea = self.crear_tarea(horas_estimadas="8.25")
        resumen = self.modulo.resumen_de_tareas([tarea])
        self.assertEqual(resumen["desviacion"], Decimal("-8.25"))
        self.assertEqual(resumen["avance"], 0)
        tarea.horas_estimadas = Decimal("0")
        self.db.session.add(self.modulo.RegistroHoras(
            tarea=tarea, usuario=self.dev, horas=Decimal("2.50"),
        ))
        self.db.session.commit()
        resumen = self.modulo.resumen_de_tareas([tarea])
        self.assertEqual(resumen["desviacion"], Decimal("2.50"))
        self.assertEqual(resumen["avance"], 0)

    def test_filtros_y_formulario_de_edicion_disponibles(self):
        tarea = self.crear_tarea()
        respuesta = self.cliente.get(f"/tareas/{tarea.id}/editar")
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn(b'form', respuesta.data)
        detalle = self.cliente.get(f"/proyectos/{self.proyecto.id}")
        for atributo in (
            'id="filtro-estado"', 'id="filtro-responsable"', 'id="filtro-fase"',
            'data-status="pendiente"', f'data-owner="{self.dev.id}"',
            f'data-phase="{self.fase.id}"',
        ):
            self.assertIn(atributo.encode(), detalle.data)

    def test_operaciones_requieren_csrf(self):
        with patch.dict(self.app.config, {"WTF_CSRF_ENABLED": True}):
            respuesta = self.cliente.post(
                f"/proyectos/{self.proyecto.id}/tareas/nueva",
                data=self.datos_tarea(),
            )
        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(self.modulo.Tarea.query.count(), 0)


if __name__ == "__main__":
    unittest.main()
