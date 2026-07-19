"""
Lógica de negocio del Kernel — idéntica en espíritu a kernel_service/app/crud.py.
Esta copia existe para que remote_server/ sea una carpeta 100% autocontenida y fácil de desplegar
(un solo servicio, sin depender de otra carpeta del repo). Ver docs/mcp.md sobre esta decisión.
"""
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import select, func
import models

ACTIVE_THRESHOLD = 70
HYPOTHESIS_THRESHOLD = 40
VOLATILIDAD_A_DIAS = {"alta": 30, "media": 90, "baja": 180}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def estado_por_confianza(confianza: float) -> str:
    if confianza >= ACTIVE_THRESHOLD:
        return "activo"
    if confianza >= HYPOTHESIS_THRESHOLD:
        return "hipotesis_abierta"
    return "descartado"


def next_insight_id(db: Session) -> str:
    count = db.scalar(select(func.count()).select_from(models.Entidad).where(models.Entidad.tipo == "insight")) or 0
    return f"INS-{count + 1:03d}"


def get_entidad(db: Session, entidad_id: str):
    return db.get(models.Entidad, entidad_id)


def crear_proyecto(db: Session, id: str, nombre: str, industria: str | None, producto: str | None,
                    publico_objetivo: str | None, objetivo_negocio: str | None):
    if db.get(models.Proyecto, id):
        return None, f"Ya existe un proyecto con id '{id}'."
    p = models.Proyecto(id=id, nombre=nombre, industria=industria, producto=producto,
                         publico_objetivo=publico_objetivo, objetivo_negocio=objetivo_negocio)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p, None


def crear_entidad(db: Session, id: str, proyecto_id: str, tipo: str, estado: str, data: dict, origen: str | None):
    if db.get(models.Entidad, id):
        return None, f"Ya existe una entidad con id '{id}'."
    if not db.get(models.Proyecto, proyecto_id):
        return None, f"El proyecto '{proyecto_id}' no existe."
    e = models.Entidad(id=id, proyecto_id=proyecto_id, tipo=tipo, estado=estado, data=data, origen=origen)
    db.add(e)
    db.commit()
    db.refresh(e)
    return e, None


def crear_insight(db: Session, proyecto_id: str, enunciado: str, confianza: float, origen: str,
                   volatilidad: str, evidencia: list, relacion_tipo: str | None, relacion_destino_id: str | None):
    if not db.get(models.Proyecto, proyecto_id):
        return None, True, f"El proyecto '{proyecto_id}' no existe.", None

    estado = estado_por_confianza(confianza)
    entidad = models.Entidad(
        id=next_insight_id(db), proyecto_id=proyecto_id, tipo="insight", estado=estado,
        confianza=confianza, volatilidad=volatilidad, origen=origen,
        data={"enunciado": enunciado}, evidencia=evidencia or [],
        fecha_creacion=now_utc(), ultima_validacion=now_utc(),
        frecuencia_revision_dias=VOLATILIDAD_A_DIAS.get(volatilidad, 90),
    )
    db.add(entidad)
    db.flush()

    if estado == "descartado":
        db.commit()
        db.refresh(entidad)
        return entidad, True, (
            f"{entidad.id} tiene {confianza}% de confianza — no entra al grafo como insight formal. "
            f"Se guarda como 'descartado' para auditoría, fuera de vistas activas y de herencia."
        ), None

    conflicto_info = None
    mensaje = f"{entidad.id} creado con estado '{estado}' ({confianza}% de confianza)."

    if relacion_tipo and relacion_destino_id:
        if not get_entidad(db, relacion_destino_id):
            mensaje += (
                f" Advertencia: no se creó la relación '{relacion_tipo}' hacia '{relacion_destino_id}' "
                f"porque esa entidad no existe todavía."
            )
        else:
            db.add(models.Relacion(origen_id=entidad.id, tipo=relacion_tipo, destino_id=relacion_destino_id))
            if relacion_tipo == "contradice":
                conflicto_info = _resolver_o_marcar_conflicto(db, entidad, relacion_destino_id)

    db.commit()
    db.refresh(entidad)
    return entidad, False, mensaje, conflicto_info


def _resolver_o_marcar_conflicto(db: Session, nuevo, objetivo_id: str):
    objetivo = get_entidad(db, objetivo_id)
    if not objetivo or objetivo.tipo != "insight" or objetivo.confianza is None:
        return None
    if nuevo.confianza > objetivo.confianza:
        objetivo.estado = "requiere_revision"
        pendiente = models.ConflictoPendiente(
            nuevo_id=nuevo.id, objetivo_id=objetivo.id,
            confianza_nueva=nuevo.confianza, confianza_objetivo=objetivo.confianza,
        )
        db.add(pendiente)
        db.flush()
        return {"tipo": "requiere_decision", "conflicto_id": pendiente.id,
                "mensaje": f"{nuevo.id} ({nuevo.confianza}%) contradice a {objetivo.id} ({objetivo.confianza}%). Queda pendiente de resolución."}
    else:
        nuevo.estado = "archivado"
        return {"tipo": "auto_resuelto",
                "mensaje": f"{nuevo.id} ({nuevo.confianza}%) contradice a {objetivo.id} ({objetivo.confianza}%) pero tiene menor o igual confianza; se archiva solo."}


def crear_relacion(db: Session, origen_id: str, tipo: str, destino_id: str):
    if not get_entidad(db, origen_id) or not get_entidad(db, destino_id):
        return None, "Origen o destino no existen."
    r = models.Relacion(origen_id=origen_id, tipo=tipo, destino_id=destino_id)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r, None


def resolver_conflicto(db: Session, conflicto_id: int, favor: str):
    conflicto = db.get(models.ConflictoPendiente, conflicto_id)
    if not conflicto:
        return None, "Conflicto no encontrado."
    if conflicto.resuelto:
        return None, "Este conflicto ya fue resuelto."
    nuevo = get_entidad(db, conflicto.nuevo_id)
    objetivo = get_entidad(db, conflicto.objetivo_id)
    if favor == "nuevo":
        db.add(models.Relacion(origen_id=nuevo.id, tipo="sustituye", destino_id=objetivo.id))
        objetivo.estado = "archivado"
        conflicto.resolucion = "favor_nuevo"
    else:
        nuevo.estado = "archivado"
        objetivo.estado = estado_por_confianza(objetivo.confianza)
        conflicto.resolucion = "favor_existente"
    conflicto.resuelto = True
    conflicto.fecha_resolucion = now_utc()
    db.commit()
    db.refresh(conflicto)
    return conflicto, None


def confianza_heredada(db: Session, entidad_id: str):
    rels = db.scalars(
        select(models.Relacion).where(models.Relacion.destino_id == entidad_id, models.Relacion.tipo == "sustenta")
    ).all()
    sustentos = []
    for r in rels:
        e = get_entidad(db, r.origen_id)
        if e and e.estado not in ("archivado", "descartado") and e.confianza is not None:
            sustentos.append(e)
    if not sustentos:
        return None, []
    return min(e.confianza for e in sustentos), [e.id for e in sustentos]


def vista_executive_report(db: Session, proyecto_id: str):
    def por_tipo_y_estado(tipos, estados=None):
        q = select(models.Entidad).where(models.Entidad.proyecto_id == proyecto_id, models.Entidad.tipo.in_(tipos))
        if estados:
            q = q.where(models.Entidad.estado.in_(estados))
        return db.scalars(q).all()

    decisiones = []
    for d in por_tipo_y_estado(["decision"], ["ejecutable"]):
        conf, sustentos = confianza_heredada(db, d.id)
        decisiones.append({"id": d.id, "accion": d.data.get("accion"), "prioridad": d.data.get("prioridad"),
                            "confianza_heredada": conf, "sustentado_por": sustentos})

    conflictos = db.scalars(select(models.ConflictoPendiente).where(models.ConflictoPendiente.resuelto == False)).all()  # noqa: E712
    conflictos_proy = [c for c in conflictos if (e := get_entidad(db, c.nuevo_id)) and e.proyecto_id == proyecto_id]

    return {
        "proyecto_id": proyecto_id,
        "estado_del_negocio": [e.data for e in por_tipo_y_estado(["mercado", "competidor"])],
        "hipotesis_activas": [{"id": e.id, "enunciado": e.data.get("enunciado"), "confianza": e.confianza}
                               for e in por_tipo_y_estado(["insight"], ["hipotesis_abierta"])],
        "conflictos_abiertos": [{"id": c.id, "nuevo_id": c.nuevo_id, "objetivo_id": c.objetivo_id} for c in conflictos_proy],
        "decisiones": decisiones,
        "nota_alcance": "'proxima_revision' no se incluye: el decaimiento temporal no está implementado todavía.",
    }
