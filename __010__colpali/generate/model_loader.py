# models/model_loader.py

import os
import torch
from transformers import MllamaForConditionalGeneration
from transformers import AutoModelForCausalLM
from transformers import AutoProcessor
import google.generativeai as genai
from groq import Groq
from openai import OpenAI
import httpx
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from __010__colpali.paths import get_logger

logger = get_logger(__name__)

# Cache for loaded models
_model_cache = {}

# Default DashScope OpenAI-compatible endpoint (China). Override with DASHSCOPE_BASE_URL if needed.
DASHSCOPE_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DASHSCOPE_DEFAULT_MODEL = "qwen-vl-plus"

# Models that only support single image processing
SINGLE_IMAGE_MODELS = {
    'ollama-llama-vision': True,
    'groq-llama-vision': True,
    'llama-vision': True,
    'pixtral': True,
    'molmo': True
}

def is_single_image_model(model_choice):
    """Returns True if the model only supports processing a single image."""
    return model_choice in SINGLE_IMAGE_MODELS

def detect_device():
    """
    Detects the best available device (CUDA, MPS, or CPU).
    """
    if torch.cuda.is_available():
        return 'cuda'
    elif torch.backends.mps.is_available():
        return 'mps'
    else:
        return 'cpu'

def load_model(model_choice):
    """
    Loads and caches the specified model.
    """
    global _model_cache

    if model_choice in _model_cache:
        logger.info(f"Model '{model_choice}' loaded from cache.")
        return _model_cache[model_choice]

    if model_choice == 'qwen':
        # Cloud Qwen-VL via Alibaba DashScope (OpenAI-compatible API). No local GPU/weights.
        api_key = os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            raise ValueError(
                "DASHSCOPE_API_KEY not found in .env. "
                "Get a key from https://dashscope.console.aliyun.com/"
            )
        base_url = os.getenv("DASHSCOPE_BASE_URL", DASHSCOPE_DEFAULT_BASE_URL)
        model_name = os.getenv("DASHSCOPE_VL_MODEL", DASHSCOPE_DEFAULT_MODEL)
        # DashScope is a China API. A broken local HTTP_PROXY (Clash etc.)
        # shows up as WinError 10061. Direct connect unless explicitly enabled.
        use_proxy = os.getenv("DASHSCOPE_USE_PROXY", "").strip().lower() in {
            "1", "true", "yes",
        }
        http_client = httpx.Client(trust_env=use_proxy, timeout=60.0)
        client = OpenAI(api_key=api_key, base_url=base_url, http_client=http_client)
        _model_cache[model_choice] = (client, model_name)
        logger.info(
            f"DashScope Qwen client cached (model={model_name}, use_proxy={use_proxy})."
        )
        return _model_cache[model_choice]

    elif model_choice == 'gemini':
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not found in .env file")
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash-002')
        return model, None

    elif model_choice == 'llama-vision':
        device = detect_device()
        model_id = "alpindale/Llama-3.2-11B-Vision-Instruct"
        model = MllamaForConditionalGeneration.from_pretrained(
            model_id,
            torch_dtype=torch.float16 if device != 'cpu' else torch.float32,
            device_map="auto"
        )
        processor = AutoProcessor.from_pretrained(model_id)
        model.to(device)
        _model_cache[model_choice] = (model, processor, device)
        logger.info("Llama-Vision model loaded and cached.")
        return _model_cache[model_choice]
    
    elif model_choice == "pixtral":
        device = detect_device()
        mistral_models_path = os.path.join(os.getcwd(), 'mistral_models', 'Pixtral')
        
        if not os.path.exists(mistral_models_path):
            os.makedirs(mistral_models_path, exist_ok=True)
            from huggingface_hub import snapshot_download
            snapshot_download(repo_id="mistralai/Pixtral-12B-2409", 
                              allow_patterns=["params.json", "consolidated.safetensors", "tekken.json"], 
                              local_dir=mistral_models_path)

        from mistral_inference.transformer import Transformer
        from mistral_common.tokens.tokenizers.mistral import MistralTokenizer
        from mistral_common.generate import generate

        tokenizer = MistralTokenizer.from_file(os.path.join(mistral_models_path, "tekken.json"))
        model = Transformer.from_folder(mistral_models_path)
        
        _model_cache[model_choice] = (model, tokenizer, generate, device)
        logger.info("Pixtral model loaded and cached.")
        return _model_cache[model_choice]
    
    elif model_choice == "molmo":
        device = detect_device()
        processor = AutoProcessor.from_pretrained(
            'allenai/MolmoE-1B-0924',
            trust_remote_code=True,
            torch_dtype='auto',
            device_map='auto'
        )
        model = AutoModelForCausalLM.from_pretrained(
            'allenai/MolmoE-1B-0924',
            trust_remote_code=True,
            torch_dtype='auto',
            device_map='auto'
        )
        _model_cache[model_choice] = (model, processor, device)
        return _model_cache[model_choice]

    elif model_choice == 'groq-llama-vision':
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY not found in .env file")
        client = Groq(api_key=api_key)
        _model_cache[model_choice] = client
        logger.info("Groq Llama Vision model loaded and cached.")
        return _model_cache[model_choice]

    elif model_choice == 'ollama-llama-vision':
        logger.info("Ollama Llama Vision model ready to use.")
        return None

    else:
        logger.error(f"Invalid model choice: {model_choice}")
        raise ValueError("Invalid model choice.")
