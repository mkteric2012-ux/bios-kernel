"""
BIOS Kernel — servidor MCP remoto (streamable-http).

Este servidor está pensado para desplegarse en un host público (Render, Railway, etc.)
y conectarse a Cowork/claude.ai como "custom connector" remoto. NO usa stdio: los
servidores MCP locales (stdio, vía claude_desktop_config.json) no son compatibles con
Cowork, que solo soporta conectores remotos alcanzables por HTTP público.

A diferencia del prototipo anterior (mcp_server/server.py, que llamaba a una API FastAPI
separada por HTTP local), este servidor llama a la lógica de negocio (crud.py) directamente
en el mismo proceso — un solo servicio que desplegar, sin partes móviles adicionales.
"""
import os

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

import database
import models
import crud

# Crea las tablas si no existen (primera vez que arranca contra una DB nueva).
models.Base.metadata.create_all(bind=database.engine)

# Por defecto, la librería MCP restringe allowed_hosts/allowed_origins a localhost como
# protección contra DNS-rebinding. En un despliegue remoto real esto bloquearía las
# solicitudes legítimas que llegan desde la infraestructura de Anthropic, así que se afloja.
transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=False,
)

mcp = FastMCP(
    name="bios-kernel",
    host="0.0.0.0",
    port=int(os.environ.get("PORT", 8000)),
    stateless_http=True,
    transport_security=transport_security,
)


def _session():
    return database.SessionLocal()


@mcp.tool()
def bios_crear_proyecto(id: str, nombre: str, industria: str = "", producto: str = "",
                         publico_objetivo: str = "", objetivo_negocio: str = "") -> dict:
    """Crea un nuevo proyecto (marca/cliente) en el Kernel de BIOS."""
    db = _session()
    try:
        p, error = crud.crear_proyecto(db, id, nombre, industria or None, producto or None,
                                        publico_objetivo or None, objetivo_negocio or None)
        if error:
            return {"ok": False, "error": error}
        return {"ok": True, "proyecto_id": p.id, "nombre": p.nombre}
    finally:
        db.close()


@mcp.tool()
def bios_crear_entidad(id: str, proyecto_id: str, tipo: str, estado: str,
                        data: dict, origen: str = "") -> dict:
    """
    Crea una entidad genérica en el grafo de BIOS (mercado, competidor, decision, kpi,
    experimento, mensaje, brand_dna, etc.). Para insights usa bios_crear_insight en su lugar,
    porque ese tool aplica el umbral de confianza y el Conflict Resolver.
    """
    db = _session()
    try:
        e, error = crud.crear_entidad(db, id, proyecto_id, tipo, estado, data, origen or None)
        if error:
            return {"ok": False, "error": error}
        return {"ok": True, "entidad_id": e.id, "tipo": e.tipo, "estado": e.estado}
    finally:
        db.close()


@mcp.tool()
def bios_crear_insight(proyecto_id: str, enunciado: str, confianza: float, origen: str,
                        volatilidad: str = "media", evidencia: list | None = None,
                        relacion_tipo: str = "", relacion_destino_id: str = "") -> dict:
    """
    Crea un insight/hipótesis con un nivel de confianza (0-100). El Kernel decide
    automáticamente su estado (activo / hipotesis_abierta / descartado) según el umbral,
    y si relacion_tipo='contradice' dispara el Conflict Resolver contra relacion_destino_id.
    """
    db = _session()
    try:
        entidad, descartado, mensaje, conflicto = crud.crear_insight(
            db, proyecto_id, enunciado, confianza, origen, volatilidad,
            evidencia or [], relacion_tipo or None, relacion_destino_id or None,
        )
        if entidad is None:
            return {"ok": False, "error": mensaje}
        resultado = {
            "ok": True, "descartado": descartado, "mensaje": mensaje,
            "entidad": {"id": entidad.id, "estado": entidad.estado, "confianza": entidad.confianza},
        }
        if conflicto:
            resultado["conflicto"] = conflicto
        return resultado
    finally:
        db.close()


@mcp.tool()
def bios_crear_relacion(origen_id: str, tipo: str, destino_id: str) -> dict:
    """Crea una relación tipada explícita entre dos entidades ya existentes (causa, modifica, genera, sustenta, afecta, contradice, sustituye, deriva_de, valida, invalida)."""
    db = _session()
    try:
        r, error = crud.crear_relacion(db, origen_id, tipo, destino_id)
        if error:
            return {"ok": False, "error": error}
        return {"ok": True, "relacion_id": r.id, "origen": r.origen_id, "tipo": r.tipo, "destino": r.destino_id}
    finally:
        db.close()


@mcp.tool()
def bios_confianza_heredada(entidad_id: str) -> dict:
    """Calcula la confianza heredada de una entidad (mínimo entre las entidades que la sustentan vía relación 'sustenta' — nunca promedio)."""
    db = _session()
    try:
        confianza, sustentado_por = crud.confianza_heredada(db, entidad_id)
        return {"ok": True, "entidad_id": entidad_id, "confianza_heredada": confianza, "sustentado_por": sustentado_por}
    finally:
        db.close()


@mcp.tool()
def bios_listar_conflictos_pendientes(proyecto_id: str) -> dict:
    """Lista los conflictos pendientes de resolución (contradicciones donde el nuevo insight tiene más confianza que el existente) para un proyecto."""
    db = _session()
    try:
        import sqlalchemy as sa
        conflictos = db.scalars(
            sa.select(models.ConflictoPendiente).where(models.ConflictoPendiente.resuelto == False)  # noqa: E712
        ).all()
        resultado = []
        for c in conflictos:
            nuevo = crud.get_entidad(db, c.nuevo_id)
            if nuevo and nuevo.proyecto_id == proyecto_id:
                resultado.append({
                    "conflicto_id": c.id, "nuevo_id": c.nuevo_id, "objetivo_id": c.objetivo_id,
                    "confianza_nueva": c.confianza_nueva, "confianza_objetivo": c.confianza_objetivo,
                })
        return {"ok": True, "conflictos": resultado}
    finally:
        db.close()


@mcp.tool()
def bios_resolver_conflicto(conflicto_id: int, favor: str) -> dict:
    """Resuelve un conflicto pendiente a favor de 'nuevo' o 'existente'. Nunca se resuelve automáticamente cuando el nuevo insight tiene más confianza — requiere esta decisión explícita."""
    db = _session()
    try:
        conflicto, error = crud.resolver_conflicto(db, conflicto_id, favor)
        if error:
            return {"ok": False, "error": error}
        return {"ok": True, "conflicto_id": conflicto.id, "resolucion": conflicto.resolucion}
    finally:
        db.close()


@mcp.tool()
def bios_listar_entidades(proyecto_id: str, tipo: str = "") -> dict:
    """Lista las entidades de un proyecto, opcionalmente filtradas por tipo."""
    db = _session()
    try:
        import sqlalchemy as sa
        q = sa.select(models.Entidad).where(models.Entidad.proyecto_id == proyecto_id)
        if tipo:
            q = q.where(models.Entidad.tipo == tipo)
        entidades = db.scalars(q).all()
        return {"ok": True, "entidades": [
            {"id": e.id, "tipo": e.tipo, "estado": e.estado, "confianza": e.confianza, "data": e.data}
            for e in entidades
        ]}
    finally:
        db.close()


@mcp.tool()
def bios_obtener_entidad(entidad_id: str) -> dict:
    """Obtiene el detalle completo de una entidad por su id."""
    db = _session()
    try:
        e = crud.get_entidad(db, entidad_id)
        if not e:
            return {"ok": False, "error": f"Entidad '{entidad_id}' no encontrada."}
        return {"ok": True, "entidad": {
            "id": e.id, "proyecto_id": e.proyecto_id, "tipo": e.tipo, "estado": e.estado,
            "confianza": e.confianza, "volatilidad": e.volatilidad, "origen": e.origen,
            "data": e.data, "evidencia": e.evidencia,
        }}
    finally:
        db.close()


@mcp.tool()
def bios_vista_executive_report(proyecto_id: str) -> dict:
    """Genera la vista de Executive Report (estado del negocio, hipótesis activas, conflictos abiertos, decisiones con confianza heredada) para un proyecto, calculada en vivo desde el grafo."""
    db = _session()
    try:
        return {"ok": True, "reporte": crud.vista_executive_report(db, proyecto_id)}
    finally:
        db.close()


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
