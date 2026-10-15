from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


RUN_IDLE = "0"
RUN_DONE = "1"
RUN_RUNNING = "2"
RUN_CANCEL = "3"
RUN_ERROR = "-1"

RAG_TEXT = "text"
RAG_VISION = "vision"
RAG_HYBRID = "hybrid"


class Base(DeclarativeBase):
    pass


class Knowledgebase(Base):
    __tablename__ = "knowledgebase"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    rag_mode: Mapped[str] = mapped_column(String(16), default=RAG_VISION)
    embd_id: Mapped[str] = mapped_column(String(128), default="text-embedding-v3")
    parser_id: Mapped[str] = mapped_column(String(32), default="naive")
    chunker_id: Mapped[str] = mapped_column(String(32), default="naive")
    vlm_id: Mapped[str] = mapped_column(String(128), default="qwen-vl-plus")
    chat_id: Mapped[str] = mapped_column(String(128), default="qwen-plus")
    page_top_n: Mapped[int] = mapped_column(Integer, default=3)
    top_n: Mapped[int] = mapped_column(Integer, default=6)
    similarity_threshold: Mapped[float] = mapped_column(Float, default=0.15)
    status: Mapped[str] = mapped_column(String(1), default="1")
    doc_num: Mapped[int] = mapped_column(Integer, default=0)
    chunk_num: Mapped[int] = mapped_column(Integer, default=0)
    page_num: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String(32), default="local")
    create_date: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    update_date: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Document(Base):
    __tablename__ = "document"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kb_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    type: Mapped[str] = mapped_column(String(32), default="")
    location: Mapped[str | None] = mapped_column(String(512), nullable=True)
    size: Mapped[int] = mapped_column(Integer, default=0)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    parser_id: Mapped[str] = mapped_column(String(32), default="naive")
    chunker_id: Mapped[str] = mapped_column(String(32), default="naive")
    index_modes: Mapped[str] = mapped_column(String(32), default="")
    run: Mapped[str] = mapped_column(String(2), default=RUN_IDLE)
    status: Mapped[str] = mapped_column(String(2), default="1")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    progress_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_num: Mapped[int] = mapped_column(Integer, default=0)
    page_num: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String(32), default="local")
    create_date: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    update_date: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Task(Base):
    __tablename__ = "task"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    doc_id: Mapped[str] = mapped_column(String(64), index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    progress_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    create_date: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Chunk(Base):
    __tablename__ = "chunk"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kb_id: Mapped[str] = mapped_column(String(64), index=True)
    doc_id: Mapped[str] = mapped_column(String(64), index=True)
    doc_name: Mapped[str] = mapped_column(String(255), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[str | None] = mapped_column(Text, nullable=True)
    available: Mapped[int] = mapped_column(Integer, default=1)


class User(Base):
    __tablename__ = "user"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="editor")
    status: Mapped[str] = mapped_column(String(1), default="1")
    daily_query_limit: Mapped[int] = mapped_column(Integer, default=100)
    daily_upload_limit: Mapped[int] = mapped_column(Integer, default=50)
    create_date: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PromptTemplate(Base):
    __tablename__ = "prompt_template"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    prompt_key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(1), default="1")


class AssistantConfig(Base):
    __tablename__ = "assistant_config"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    assistant_key: Mapped[str] = mapped_column(String(64), unique=True)
    assistant_name: Mapped[str] = mapped_column(String(128), default="默认助理")
    prompt_key: Mapped[str] = mapped_column(String(64), default="default")
    kb_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chat_id: Mapped[str] = mapped_column(String(128), default="qwen-plus")
    memory_rounds: Mapped[int] = mapped_column(Integer, default=5)
    status: Mapped[str] = mapped_column(String(1), default="1")


class QuotaUsage(Base):
    __tablename__ = "quota_usage"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    day: Mapped[str] = mapped_column(String(10), index=True)
    queries: Mapped[int] = mapped_column(Integer, default=0)
    uploads: Mapped[int] = mapped_column(Integer, default=0)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(64), default="")
    target: Mapped[str] = mapped_column(String(255), default="")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    create_date: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Conversation(Base):
    __tablename__ = "conversation"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kb_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_id: Mapped[str] = mapped_column(String(64), default="local")
    create_date: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    update_date: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
