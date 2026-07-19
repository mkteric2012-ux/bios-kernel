from datetime import datetime, timezone
from sqlalchemy import String, Float, Boolean, ForeignKey, JSON, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column
from database import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Proyecto(Base):
    __tablename__ = "proyectos"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    nombre: Mapped[str] = mapped_column(String)
    industria: Mapped[str | None] = mapped_column(String, nullable=True)
    producto: Mapped[str | None] = mapped_column(String, nullable=True)
    publico_objetivo: Mapped[str | None] = mapped_column(String, nullable=True)
    objetivo_negocio: Mapped[str | None] = mapped_column(String, nullable=True)
    fecha_creacion: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Entidad(Base):
    __tablename__ = "entidades"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    proyecto_id: Mapped[str] = mapped_column(String, ForeignKey("proyectos.id"))
    tipo: Mapped[str] = mapped_column(String)
    estado: Mapped[str] = mapped_column(String)
    confianza: Mapped[float | None] = mapped_column(Float, nullable=True)
    volatilidad: Mapped[str | None] = mapped_column(String, nullable=True)
    origen: Mapped[str | None] = mapped_column(String, nullable=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    evidencia: Mapped[list] = mapped_column(JSON, default=list)
    fecha_creacion: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    ultima_validacion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    caducidad: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    frecuencia_revision_dias: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Relacion(Base):
    __tablename__ = "relaciones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    origen_id: Mapped[str] = mapped_column(String, ForeignKey("entidades.id"))
    tipo: Mapped[str] = mapped_column(String)
    destino_id: Mapped[str] = mapped_column(String, ForeignKey("entidades.id"))
    fecha_creacion: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ConflictoPendiente(Base):
    __tablename__ = "conflictos_pendientes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nuevo_id: Mapped[str] = mapped_column(String, ForeignKey("entidades.id"))
    objetivo_id: Mapped[str] = mapped_column(String, ForeignKey("entidades.id"))
    confianza_nueva: Mapped[float] = mapped_column(Float)
    confianza_objetivo: Mapped[float] = mapped_column(Float)
    resuelto: Mapped[bool] = mapped_column(Boolean, default=False)
    resolucion: Mapped[str | None] = mapped_column(String, nullable=True)
    fecha_creacion: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    fecha_resolucion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
