import time
import jwt
import datetime
from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_caching import Cache
from sqlalchemy.orm import joinedload
from celery import Celery
from flask_cors import CORS
import mysql.connector
from datetime import date
from werkzeug.security import check_password_hash, generate_password_hash

# -------------------
# CONFIGURACIÓN INICIAL
# -------------------
app = Flask(__name__)
CORS(app)

app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:@localhost/celactive_db'
app.config['SQLALCHEMY_ECHO'] = True
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'CAMBIA_ESTA_CLAVE_SEGURA'  # Cambia esta clave por una más robusta

cache = Cache(app, config={'CACHE_TYPE': 'SimpleCache', 'CACHE_DEFAULT_TIMEOUT': 300})
db = SQLAlchemy(app)

# -------------------
# CONFIGURACIÓN CELERY
# -------------------
def make_celery(app):
    celery = Celery(
        app.import_name,
        broker='sqla+sqlite:///celery_tasks.db',
        backend='db+sqlite:///celery_tasks.db'
    )
    celery.conf.update(app.config)
    return celery

celery = make_celery(app)

# -------------------
# MODELOS
# -------------------
class Cliente(db.Model):
    __tablename__ = 'clientes'
    id_cliente = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    telefono = db.Column(db.String(20))
    correo = db.Column(db.String(100), unique=True, nullable=False)
    contraseña = db.Column(db.String(255), nullable=False)

class Servicio(db.Model):
    __tablename__ = 'servicios'
    id_servicio = db.Column(db.Integer, primary_key=True)
    nombre_servicio = db.Column(db.String(100), nullable=False)
    costo_base = db.Column(db.Numeric(10, 2), nullable=False)
    tipo = db.Column(db.String(50), nullable=False)

class OrdenServicio(db.Model):
    __tablename__ = 'ordenes'

    id_orden = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.Date, nullable=False, default=date.today)
    estado = db.Column(db.String(50), default='pendiente')
    descripcion = db.Column(db.String(255), nullable=False)
    costo = db.Column(db.Numeric(10, 2), nullable=False)

    id_cliente = db.Column(
        db.Integer,
        db.ForeignKey('clientes.id_cliente')
    )

    id_servicio = db.Column(
        db.Integer,
        db.ForeignKey('servicios.id_servicio')
    )

    cliente = db.relationship('Cliente', backref='ordenes')
    servicio = db.relationship('Servicio', backref='ordenes')

# -------------------
# TAREA ASÍNCRONA
# -------------------
@celery.task(name='tarea_enviar_notificacion')
def tarea_enviar_notificacion(orden_id, email_cliente):
    time.sleep(10)
    return f"Notificación enviada para la orden {orden_id} a {email_cliente}"

# -------------------
# CONEXIÓN DIRECTA MYSQL
# -------------------
conexion = mysql.connector.connect(
    host="localhost",
    user="root",
    password="",
    database="celactive_db"
)

# -------------------
# RUTAS DE SERVICIOS
# -------------------
@app.route('/servicios', methods=['GET'])
def obtener_servicios():
    servicios = Servicio.query.all()
    resultado = [{
        "id_servicio": s.id_servicio,
        "nombre_servicio": s.nombre_servicio,
        "costo_base": str(s.costo_base),
        "tipo": s.tipo
    } for s in servicios]
    return jsonify(resultado)

@app.route('/servicios', methods=['POST'])
def crear_servicio():
    data = request.get_json()
    nombre = data.get('nombre_servicio')
    costo = data.get('costo_base')
    tipo = data.get('tipo')

    if not nombre or not costo or not tipo:
        return jsonify({'status': 'error', 'message': 'Faltan datos'}), 400

    nuevo = Servicio(nombre_servicio=nombre, costo_base=costo, tipo=tipo)
    db.session.add(nuevo)
    db.session.commit()
    return jsonify({'status': 'ok', 'message': 'Servicio creado correctamente'})

@app.route('/servicios/<int:id_servicio>', methods=['PUT'])
def actualizar_servicio(id_servicio):
    data = request.get_json()
    servicio = Servicio.query.get(id_servicio)
    if not servicio:
        return jsonify({'status': 'error', 'message': 'Servicio no encontrado'}), 404

    servicio.nombre_servicio = data.get('nombre_servicio', servicio.nombre_servicio)
    servicio.costo_base = data.get('costo_base', servicio.costo_base)
    servicio.tipo = data.get('tipo', servicio.tipo)
    db.session.commit()
    return jsonify({'status': 'ok', 'message': 'Servicio actualizado correctamente'})

@app.route('/servicios/<int:id_servicio>', methods=['DELETE'])
def eliminar_servicio(id_servicio):
    servicio = Servicio.query.get(id_servicio)
    if not servicio:
        return jsonify({'status': 'error', 'message': 'Servicio no encontrado'}), 404

    db.session.delete(servicio)
    db.session.commit()
    return jsonify({'status': 'ok', 'message': 'Servicio eliminado correctamente'})

# -------------------
# RUTAS DE ORDENES
# -------------------
@app.route('/ordenes', methods=['GET'])
def obtener_ordenes():
    ordenes = OrdenServicio.query.options(joinedload(OrdenServicio.cliente), joinedload(OrdenServicio.servicio)).all()
    resultado = [{
        "id_orden": o.id_orden,
        "fecha": str(o.fecha),
        "estado": o.estado,
        "descripcion": o.descripcion,
        "costo": str(o.costo),
        "cliente": o.cliente.nombre if o.cliente else "Sin cliente",
        "servicio": o.servicio.nombre_servicio if o.servicio else "Sin servicio"
    } for o in ordenes]
    return jsonify(resultado)

@app.route('/historial/<int:id_cliente>', methods=['GET'])
def historial_cliente(id_cliente):

    ordenes = (
        OrdenServicio.query
        .filter_by(id_cliente=id_cliente)
        .join(Servicio)
        .all()
    )

    resultado = [{
        "id_orden": o.id_orden,
        "nombre_servicio": o.servicio.nombre_servicio,
        "estado": o.estado,
        "fecha": str(o.fecha),
        "costo": str(o.costo)
    } for o in ordenes]

    return jsonify(resultado)

# -------------------
# AUTENTICACIÓN JWT
# -------------------
@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'message': 'No se recibieron datos JSON'}), 400

    correo = data.get('correo')
    contraseña = data.get('contrasena') or data.get('contraseña')

    if not correo or not contraseña:
        return jsonify({'status': 'error', 'message': 'Faltan datos'}), 400

    cliente = Cliente.query.filter_by(correo=correo).first()
    if cliente and check_password_hash(
        cliente.contraseña,
        contraseña):
        token = jwt.encode({
            'id_cliente': cliente.id_cliente,
            'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=2)
        }, app.config['SECRET_KEY'], algorithm="HS256")

        return jsonify({
            'status': 'ok',
            'user': cliente.nombre,
            'id_cliente': cliente.id_cliente,
            'telefono': cliente.telefono,
            'token': token
        })
    else:
        return jsonify({'status': 'error', 'message': 'Credenciales inválidas'}), 401

@app.route('/register', methods=['POST'])
def register():
    try:

        data = request.get_json()

        print("DATOS RECIBIDOS:", data)

        nombre = data.get('nombre')
        correo = data.get('correo')
        contraseña = data.get('contrasena')
        telefono = data.get('telefono')

        existe = Cliente.query.filter_by(
            correo=correo
        ).first()

        if existe:
            return jsonify({
                'status': 'error',
                'message': 'El correo ya existe'
            }), 409

        nuevo = Cliente(
            nombre=nombre,
            correo=correo,
            telefono=telefono,
            contraseña=generate_password_hash(
                contraseña
            )
        )

        db.session.add(nuevo)
        db.session.commit()

        print("USUARIO GUARDADO")

        return jsonify({
            'status': 'ok',
            'message': 'Usuario registrado correctamente'
        }), 201

    except Exception as e:

        db.session.rollback()

        print("ERROR REGISTER:")
        print(str(e))

        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

# -------------------
# MAIN
# -------------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
