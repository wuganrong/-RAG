"""Concrete chunkers built on yf-rag ParsedDocument objects."""

from __future__ import annotations

# 1. Python 标准库
import re
from typing import Any

# 2. 第三方库
from django.conf import settings
from loguru import logger

# 3. 本地应用
from __001__rag.chunk.base import BaseChunker, ChunkContext, ChunkItem
from __001__rag.chunk.macbert import MacBERTChunker
from __001__rag.chunk.utils import (
    TextSection,
    build_token_metadata,
    document_sections,
    document_text,
    estimate_token_count,
    extract_markdown_tables,
    extract_qa_sections,
    extract_tag_sections,
    make_chunk_id,
    split_text_by_token_budget,
)
from __001__rag.chunk.utils.pdf_llm import (
    chunk_section_with_llm,
    extract_gb_standard_from_filename,
    fix_clause_numbers,
    sections_with_parent,
    write_sections_to_file,
)
from __001__rag.chunk.utils.pdf_llm import PARSE_METHOD_MINERU
from __001__rag.parse.base import ParsedDocument
from __001__rag.parse.utils.mineru_split import split_by_headings, split_by_toc


class MarkdownChunker(BaseChunker):
    """General Markdown/text chunker."""

    chunker_id = "naive"

    def chunk(self, document: ParsedDocument, context: ChunkContext) -> list[ChunkItem]:
        return self._sections_to_chunks(document, context, self._source_sections(document, context))

    def _source_sections(self, document: ParsedDocument, context: ChunkContext) -> list[TextSection]:
        return document_sections(document)

    def _sections_to_chunks(
        self,
        document: ParsedDocument,
        context: ChunkContext,
        sections: list[TextSection],
        *,
        extra_metadata: dict[str, Any] | None = None,
    ) -> list[ChunkItem]:
        max_tokens = int(context.config.get("chunk_token_num") or context.config.get("chunk_tokens") or 512)
        delimiter = str(context.config.get("delimiter") or "\n\n")
        chunks: list[ChunkItem] = []
        for section in sections:
            parts = split_text_by_token_budget(section.content, max_tokens, delimiter)
            for part in parts:
                metadata = self._metadata(document, context, section, part, len(chunks), extra_metadata)
                chunks.append(
                    ChunkItem(
                        content=part,
                        doc_id=context.doc_id,
                        kb_id=context.kb_id,
                        chunk_id=make_chunk_id(context.doc_id, len(chunks), part),
                        title=section.title,
                        page=section.page,
                        token_num=estimate_token_count(part),
                        metadata=metadata,
                    )
                )
        return chunks

    def _metadata(
        self,
        document: ParsedDocument,
        context: ChunkContext,
        section: TextSection,
        content: str,
        order: int,
        extra_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "docnm_kwd": document.filename,
            "parser_id": context.parser_id,
            "chunker_id": self.chunker_id,
            "chunk_order": order,
        }
        metadata.update(build_token_metadata(content, section.title))
        metadata.update(document.metadata or {})
        metadata.update(section.metadata or {})
        metadata.update(extra_metadata or {})
        metadata["parser_id"] = context.parser_id
        metadata["chunker_id"] = self.chunker_id
        return metadata


class OneChunker(MarkdownChunker):
    """Whole document as one chunk."""

    chunker_id = "one"

    def _source_sections(self, document: ParsedDocument, context: ChunkContext) -> list[TextSection]:
        text = document_text(document)
        return [TextSection(title=document.filename, content=text, metadata={"strategy": "one"})] if text else []


class TableChunker(MarkdownChunker):
    """Chunk table elements or Markdown tables."""

    chunker_id = "table"

    def _source_sections(self, document: ParsedDocument, context: ChunkContext) -> list[TextSection]:
        sections: list[TextSection] = []
        for element in document.elements:
            content = (element.content or "").strip()
            if not content:
                continue
            if element.element_type == "table":
                sections.append(
                    TextSection(
                        title=element.title or "table",
                        content=content,
                        page=element.page,
                        metadata={"element_type": "table", **(element.metadata or {})},
                    )
                )
            else:
                sections.extend(extract_markdown_tables(content))
        return sections or document_sections(document)


class QAChunker(MarkdownChunker):
    """Chunk Q&A style content."""

    chunker_id = "qa"

    def _source_sections(self, document: ParsedDocument, context: ChunkContext) -> list[TextSection]:
        sections = extract_qa_sections(document_text(document))
        return sections or document_sections(document)

    def _metadata(
        self,
        document: ParsedDocument,
        context: ChunkContext,
        section: TextSection,
        content: str,
        order: int,
        extra_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = super()._metadata(document, context, section, content, order, extra_metadata)
        if section.metadata and section.metadata.get("question"):
            metadata["question_kwd"] = section.metadata["question"]
        return metadata


class TagChunker(MarkdownChunker):
    """Chunk content/tag rows."""

    chunker_id = "tag"

    def _source_sections(self, document: ParsedDocument, context: ChunkContext) -> list[TextSection]:
        sections = extract_tag_sections(document_text(document))
        return sections or document_sections(document)


class PaperChunker(MarkdownChunker):
    """Paper-oriented chunker preserving section metadata."""

    chunker_id = "paper"

    def _metadata(
        self,
        document: ParsedDocument,
        context: ChunkContext,
        section: TextSection,
        content: str,
        order: int,
        extra_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = super()._metadata(document, context, section, content, order, extra_metadata)
        if section.title:
            metadata["section_kwd"] = section.title
            if "摘要" in section.title or section.title.lower() in {"abstract", "summary"}:
                metadata["important_kwd"] = ["abstract"]
        return metadata


class BookChunker(MarkdownChunker):
    """Book-oriented section chunker."""

    chunker_id = "book"

    def _metadata(
        self,
        document: ParsedDocument,
        context: ChunkContext,
        section: TextSection,
        content: str,
        order: int,
        extra_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = super()._metadata(document, context, section, content, order, extra_metadata)
        if section.title:
            metadata["chapter_kwd"] = section.title
        return metadata


class ManualChunker(BookChunker):
    """Manual-oriented section chunker."""

    chunker_id = "manual"

    def _metadata(
        self,
        document: ParsedDocument,
        context: ChunkContext,
        section: TextSection,
        content: str,
        order: int,
        extra_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = super()._metadata(document, context, section, content, order, extra_metadata)
        metadata["manual_section_kwd"] = section.title or ""
        return metadata


class PdfLLMChunker(PaperChunker):
    """PDF-LLM parser compatible Markdown chunker."""

    chunker_id = "pdf_llm"

    def _metadata(
        self,
        document: ParsedDocument,
        context: ChunkContext,
        section: TextSection,
        content: str,
        order: int,
        extra_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = super()._metadata(document, context, section, content, order, extra_metadata)
        if section.title:
            metadata["path_kwd"] = section.title
            metadata["topic_kwd"] = section.title
        return metadata


def _normalize_mineru_title(title: str) -> str:
    title = re.sub(r"[（(][^）)]*[）)]", "", title).strip()
    return title.replace("/", ">")


def _mineru_weighted_content(std_no: str, title: str, content: str) -> str:
    title_part = f"{title}\n\n{content}".strip()
    return f"{std_no}>{title_part}" if std_no else title_part


def _notify(callback: Any, progress: float, message: str) -> None:
    if callable(callback):
        callback(progress, message)


class MinerUChunker(PdfLLMChunker):
    """MinerU Markdown chunker preserving parser metadata."""

    chunker_id = "mineru"

    def chunk(self, document: ParsedDocument, context: ChunkContext) -> list[ChunkItem]:
        markdown_content = document_text(document)
        if not markdown_content.strip():
            return []

        sections = self._mineru_sections(markdown_content, context)
        if not sections:
            raise ValueError("MinerU 未解析到目录/标题，请选择其他解析方式")

        sections = sections_with_parent(sections)
        write_sections_to_file(document.filename, sections)
        return self._llm_sections_to_chunks(document, context, sections)

    def _mineru_sections(self, markdown_content: str, context: ChunkContext) -> list[dict[str, Any]]:
        fixed_content = fix_clause_numbers(markdown_content)
        sections = split_by_toc(fixed_content)
        if sections:
            logger.info("MinerU 按目录切分完成 section_count={}", len(sections))
            return sections

        max_section_chars = int(
            context.config.get("mineru_max_section_chars")
            or getattr(settings, "MINERU_MAX_SECTION_CHARS", None)
            or getattr(settings, "PDF_LLM_MAX_SECTION_CHARS", 20000)
        )
        sections = split_by_headings(fixed_content, max_section_chars=max_section_chars)
        logger.info("MinerU 按标题回退切分完成 section_count={}", len(sections))
        return sections

    def _llm_sections_to_chunks(
        self,
        document: ParsedDocument,
        context: ChunkContext,
        sections: list[dict[str, Any]],
    ) -> list[ChunkItem]:
        callback = context.config.get("callback")
        std_no = extract_gb_standard_from_filename(document.filename) or ""
        chunks: list[ChunkItem] = []
        total = len(sections)

        for idx, section in enumerate(sections):
            progress = 0.45 + 0.35 * (idx / total) if total else 0.6
            _notify(callback, progress, f"mineru LLM 分块 {idx + 1}/{total}")
            llm_chunks = chunk_section_with_llm(
                section,
                callback=callback,
                doc_id=context.doc_id,
                kb_id=context.kb_id,
                file_name=document.filename,
                parse_method=PARSE_METHOD_MINERU,
            )
            chunks.extend(self._build_llm_chunk_items(document, context, llm_chunks, std_no, len(chunks)))

        _notify(callback, 0.95, "mineru 分块完成")
        logger.info("MinerU 分块完成 filename={} chunk_count={}", document.filename, len(chunks))
        return chunks

    def _build_llm_chunk_items(
        self,
        document: ParsedDocument,
        context: ChunkContext,
        llm_chunks: list[dict[str, str]],
        std_no: str,
        start_order: int,
    ) -> list[ChunkItem]:
        items: list[ChunkItem] = []
        for offset, llm_chunk in enumerate(llm_chunks):
            order = start_order + offset + 1
            title = _normalize_mineru_title(llm_chunk.get("title") or "")
            content = (llm_chunk.get("content") or "").strip()
            weighted_content = _mineru_weighted_content(std_no, title, content)
            metadata = self._mineru_metadata(document, context, llm_chunk, title, weighted_content, std_no, order)
            items.append(
                ChunkItem(
                    content=weighted_content,
                    doc_id=context.doc_id,
                    kb_id=context.kb_id,
                    chunk_id=make_chunk_id(context.doc_id, order - 1, weighted_content),
                    title=title,
                    token_num=estimate_token_count(weighted_content),
                    metadata=metadata,
                )
            )
        return items

    def _mineru_metadata(
        self,
        document: ParsedDocument,
        context: ChunkContext,
        llm_chunk: dict[str, str],
        title: str,
        weighted_content: str,
        std_no: str,
        order: int,
    ) -> dict[str, Any]:
        subject = llm_chunk.get("subject") or ""
        metadata: dict[str, Any] = {
            "docnm_kwd": document.filename,
            "parser_id": context.parser_id,
            "chunker_id": self.chunker_id,
            "path_kwd": title,
            "subject_kwd": subject,
            "std_kwd": std_no,
            "topic_kwd": subject,
            "section_kwd": llm_chunk.get("section_ref") or "",
            "chunk_order": order,
        }
        metadata.update(build_token_metadata(weighted_content, document.filename))
        metadata.update(document.metadata or {})
        metadata["parser_id"] = context.parser_id
        metadata["chunker_id"] = self.chunker_id
        return metadata


class OCRFluxChunker(MarkdownChunker):
    """OCRFlux chunker, optionally using independent MacBERT parent-child chunking."""

    chunker_id = "use_ocrflux"

    def chunk(self, document: ParsedDocument, context: ChunkContext) -> list[ChunkItem]:
        if self._should_use_macbert(context):
            return self._macbert_chunks(document, context)
        return super().chunk(document, context)

    @staticmethod
    def _should_use_macbert(context: ChunkContext) -> bool:
        method = str(context.config.get("chunk_method") or context.config.get("chunker") or "").lower()
        return bool(context.config.get("use_macbert")) or method == "macbert"

    def _macbert_chunks(self, document: ParsedDocument, context: ChunkContext) -> list[ChunkItem]:
        macbert = MacBERTChunker(
            model_name=context.config.get("macbert_model_name"),
            chunk_token_num=context.config.get("macbert_chunk_token_num"),
            parent_group_size=context.config.get("macbert_parent_group_size"),
        )
        items: list[ChunkItem] = []
        text = document_text(document)
        for macbert_chunk in macbert.chunk_text(text):
            section = TextSection(title=document.filename, content=macbert_chunk.content, metadata=macbert_chunk.metadata)
            metadata = self._metadata(document, context, section, macbert_chunk.content, len(items))
            items.append(
                ChunkItem(
                    content=macbert_chunk.content,
                    doc_id=context.doc_id,
                    kb_id=context.kb_id,
                    chunk_id=make_chunk_id(context.doc_id, len(items), macbert_chunk.content),
                    title=document.filename,
                    token_num=macbert_chunk.token_num,
                    metadata=metadata,
                )
            )
        return items
