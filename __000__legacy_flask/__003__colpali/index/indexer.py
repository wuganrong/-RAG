# models/indexer.py

import os
from byaldi import RAGMultiModalModel
from __003__colpali.index.converters import convert_docs_to_pdfs
from __003__colpali.local_paths import get_default_indexer_model, resolve_indexer_model
from __000__common.__002__log import get_logger

logger = get_logger(__name__)

def index_documents(folder_path, index_name='document_index', index_path=None, indexer_model=None):
    """
    Indexes documents in the specified folder using Byaldi.

    Args:
        folder_path (str): The path to the folder containing documents to index.
        index_name (str): The name of the index to create or update.
        index_path (str): The path where the index should be saved.
        indexer_model (str): Local path or HuggingFace id for the indexer model.

    Returns:
        RAGMultiModalModel: The RAG model with the indexed documents.
    """
    try:
        if indexer_model is None:
            indexer_model = get_default_indexer_model()
        indexer_model = resolve_indexer_model(indexer_model)
        logger.info(f"Starting document indexing: {folder_path}")
        from __003__colpali.index.converters import convert_file_to_pdf

        if os.path.isfile(folder_path):
            folder_path = convert_file_to_pdf(folder_path)
        else:
            convert_docs_to_pdfs(folder_path)
        logger.info("Conversion of non-PDF documents to PDFs completed.")

        # Initialize RAG model (local path preferred when available)
        logger.info(f"Loading indexer model from: {indexer_model}")
        from __000__common.__001__path import BYALDI_DIR

        index_root = os.path.dirname(index_path) if index_path else BYALDI_DIR
        RAG = RAGMultiModalModel.from_pretrained(indexer_model, index_root=index_root)
        if RAG is None:
            raise ValueError(f"Failed to initialize RAGMultiModalModel with model {indexer_model}")
        logger.info(f"RAG model initialized with {indexer_model}.")

        # Index the documents in the folder
        RAG.index(
            input_path=folder_path,
            index_name=index_name,
            store_collection_with_index=True,
            overwrite=True
        )

        logger.info(f"Indexing completed. Index saved at '{index_path}'.")

        return RAG
    except Exception as e:
        logger.error(f"Error during indexing: {str(e)}", exc_info=True)
        raise