# models/converters.py

import os
from docx2pdf import convert
from __000__common.__002__log import get_logger

logger = get_logger(__name__)

def convert_file_to_pdf(path: str) -> str:
    """Convert one Word file to PDF. Other types are returned unchanged."""
    lower = path.lower()
    if lower.endswith((".doc", ".docx")):
        pdf_path = os.path.splitext(path)[0] + ".pdf"
        try:
            convert(path, pdf_path)
        except Exception as exc:
            raise RuntimeError("Word 转 PDF 失败。请安装本机 Word，或直接上传 PDF / 图片。") from exc
        logger.info("Converted '%s' to PDF.", os.path.basename(path))
        return pdf_path
    return path


def convert_docs_to_pdfs(folder_path):
    """
    Converts .doc and .docx files in the folder to PDFs.

    Args:
        folder_path (str): The path to the folder containing documents.
    """
    try:
        for filename in os.listdir(folder_path):
            if filename.lower().endswith(('.doc', '.docx')):
                doc_path = os.path.join(folder_path, filename)
                pdf_path = os.path.splitext(doc_path)[0] + '.pdf'
                convert(doc_path, pdf_path)
                logger.info(f"Converted '{filename}' to PDF.")
    except Exception as e:
        logger.error(f"Error converting documents to PDFs: {e}")
        raise