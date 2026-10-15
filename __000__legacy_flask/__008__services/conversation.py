from __future__ import annotations

import json
import os

import markdown
from markupsafe import Markup

from __000__common.__001__path import PAGE_IMAGE_DIR, page_abs_path, page_relpath
from __000__common.__003__orm.db import session_scope
from __000__common.__003__orm.ids import new_id
from __000__common.__003__orm.models import RUN_DONE, Conversation, Document, Knowledgebase
from __005__retrieval.fusion import retrieve_for_kb
from __006__llm.factory import generate_chat, generate_chat_stream, generate_vlm
from __008__services.assistant import render_prompt, resolve_assistant


def list_conversations(kb_id: str | None = None) -> list[dict]:
    with session_scope() as session:
        q = session.query(Conversation)
        if kb_id:
            q = q.filter(Conversation.kb_id == kb_id)
        rows = q.order_by(Conversation.update_date.desc()).all()
        return [_conv_brief(row) for row in rows]


def get_conversation(conv_id: str) -> dict | None:
    with session_scope() as session:
        row = session.get(Conversation, conv_id)
        if row is None:
            return None
        messages = json.loads(row.message or "[]")
        for msg in messages:
            if msg.get("images"):
                msg["images"] = [page_relpath(p) for p in msg["images"]]
        return _conv_brief(row) | {"messages": messages, "reference": json.loads(row.reference or "[]")}


def create_conversation(kb_id: str, name: str = "新会话", user_id: str = "local") -> dict:
    with session_scope() as session:
        kb = session.get(Knowledgebase, kb_id)
        if kb is None:
            raise ValueError("知识库不存在")
        row = Conversation(
            id=new_id(),
            kb_id=kb_id,
            name=name,
            message="[]",
            reference="[]",
            user_id=user_id or "local",
        )
        session.add(row)
        session.flush()
        return _conv_brief(row) | {"messages": []}


def rename_conversation(conv_id: str, name: str) -> dict:
    with session_scope() as session:
        row = session.get(Conversation, conv_id)
        if row is None:
            raise ValueError("会话不存在")
        row.name = name
        session.flush()
        return _conv_brief(row)


def delete_conversation(conv_id: str) -> None:
    with session_scope() as session:
        row = session.get(Conversation, conv_id)
        if row is not None:
            session.delete(row)


def ready_doc_count(kb_id: str) -> int:
    with session_scope() as session:
        return (
            session.query(Document)
            .filter(Document.kb_id == kb_id, Document.run == RUN_DONE, Document.status == "1")
            .count()
        )


def ask(
    conv_id: str,
    query: str,
    index_root: str,
    static_folder: str,
    resized_height: int = 280,
    resized_width: int = 280,
    generation_model: str = "qwen",
) -> dict:
    with session_scope() as session:
        conv = session.get(Conversation, conv_id)
        if conv is None:
            raise ValueError("会话不存在")
        kb = session.get(Knowledgebase, conv.kb_id)
        if kb is None:
            raise ValueError("知识库不存在")
        ready = (
            session.query(Document)
            .filter(Document.kb_id == kb.id, Document.run == RUN_DONE, Document.status == "1")
            .count()
        )
        if ready <= 0:
            raise ValueError("当前知识库还没有完成建索的文档。请先上传并等待 Indexing 完成后再提问。")

        retrieved = retrieve_for_kb(session, kb, query, index_root)
        chunks = retrieved["chunks"]
        pages = retrieved["pages"]
        if not chunks and not pages:
            raise ValueError("没有检索到足够依据，无法回答。请换个问法或检查文档是否已建索。")

        assistant = resolve_assistant(kb.id)
        history = _history_text(json.loads(conv.message or "[]"), assistant["memory_rounds"])
        chunk_context = "\n\n".join(f"[{i+1}] {c['doc_name']}: {c['content']}" for i, c in enumerate(chunks[:6]))
        prompt = render_prompt(assistant["prompt"], query, chunk_context, history)
        images = [p["image"] for p in pages if p.get("image")]
        used_images: list[str] = []
        if images:
            image_root = static_folder or PAGE_IMAGE_DIR
            full_paths = [page_abs_path(img) if image_root == PAGE_IMAGE_DIR else os.path.join(image_root, img) for img in images]
            text, used = generate_vlm(
                full_paths,
                query,
                kb.id,
                extra_context=chunk_context,
                resized_height=resized_height,
                resized_width=resized_width,
                model_choice=generation_model,
                vlm_id=kb.vlm_id,
            )
            used_images = [page_relpath(os.path.relpath(p, PAGE_IMAGE_DIR)) for p in used]
        else:
            text = generate_chat(query, chunk_context, model=assistant["chat_id"] or kb.chat_id, prompt=prompt)

        citations = chunks + pages
        parsed = Markup(markdown.markdown(text))
        _save_turn(conv, query, str(parsed), used_images, citations)
        return {
            "answer_html": parsed,
            "images": used_images,
            "citations": citations,
            "session_name": conv.name,
        }


def ask_stream(
    conv_id: str,
    query: str,
    index_root: str,
    static_folder: str,
    generation_model: str = "qwen",
    resized_height: int = 280,
    resized_width: int = 280,
):
    with session_scope() as session:
        conv = session.get(Conversation, conv_id)
        if conv is None:
            raise ValueError("会话不存在")
        kb = session.get(Knowledgebase, conv.kb_id)
        if kb is None:
            raise ValueError("知识库不存在")
        ready = (
            session.query(Document)
            .filter(Document.kb_id == kb.id, Document.run == RUN_DONE, Document.status == "1")
            .count()
        )
        if ready <= 0:
            raise ValueError("当前知识库还没有完成建索的文档。")
        retrieved = retrieve_for_kb(session, kb, query, index_root)
        chunks = retrieved["chunks"]
        pages = retrieved["pages"]
        if not chunks and not pages:
            raise ValueError("没有检索到足够依据，无法回答。")
        assistant = resolve_assistant(kb.id)
        history = _history_text(json.loads(conv.message or "[]"), assistant["memory_rounds"])
        chunk_context = "\n\n".join(f"[{i+1}] {c['doc_name']}: {c['content']}" for i, c in enumerate(chunks[:6]))
        prompt = render_prompt(assistant["prompt"], query, chunk_context, history)
        conv_id_saved = conv.id
        kb_id = kb.id
        chat_model = kb.chat_id or assistant["chat_id"]
        vlm_id = kb.vlm_id
        citations = chunks + pages
        images = [p["image"] for p in pages if p.get("image")]

    yield {"event": "citations", "citations": citations, "images": images}
    if images:
        full_paths = [page_abs_path(img) for img in images]
        text, used = generate_vlm(
            full_paths,
            query,
            kb_id,
            extra_context=chunk_context,
            resized_height=resized_height,
            resized_width=resized_width,
            model_choice=generation_model,
            vlm_id=vlm_id,
        )
        yield {"event": "token", "text": text}
        used_images = [page_relpath(os.path.relpath(p, PAGE_IMAGE_DIR)) for p in used]
        full = text
    else:
        full = ""
        used_images = []
        for token in generate_chat_stream(prompt, model=chat_model):
            full += token
            yield {"event": "token", "text": token}

    with session_scope() as session:
        conv = session.get(Conversation, conv_id_saved)
        if conv is not None:
            parsed = str(Markup(markdown.markdown(full)))
            _save_turn(conv, query, parsed, used_images, citations)
    yield {"event": "done", "answer_html": str(Markup(markdown.markdown(full))), "images": used_images, "citations": citations}


def _history_text(messages: list, rounds: int) -> str:
    pairs = messages[-(max(rounds, 0) * 2) :] if rounds else []
    lines = []
    for msg in pairs:
        role = "用户" if msg.get("role") == "user" else "助手"
        content = msg.get("content") or ""
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _save_turn(conv: Conversation, query: str, answer_html: str, images: list, citations: list) -> None:
    messages = json.loads(conv.message or "[]")
    messages.append({"role": "user", "content": query})
    messages.append({"role": "assistant", "content": answer_html, "images": images, "citations": citations})
    if len(messages) == 2:
        conv.name = query[:50]
    conv.message = json.dumps(messages, ensure_ascii=False)
    conv.reference = json.dumps(citations, ensure_ascii=False)


def _conv_brief(row: Conversation) -> dict:
    return {
        "id": row.id,
        "kb_id": row.kb_id,
        "name": row.name or "未命名会话",
        "user_id": row.user_id or "local",
    }
