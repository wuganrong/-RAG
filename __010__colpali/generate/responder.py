# models/responder.py

from __010__colpali.generate.model_loader import load_model, is_single_image_model
from transformers import GenerationConfig
import google.generativeai as genai
from dotenv import load_dotenv
from __010__colpali.paths import get_logger
from openai import OpenAI, APIConnectionError
from PIL import Image
import torch
import base64
import os
import io
import time
# from langchain_core.messages import HumanMessage
from io import BytesIO
import ollama


logger = get_logger(__name__)


def _resolve_image_path(img: str) -> str:
    from __010__colpali.paths import page_abs_path

    if not img:
        return img
    if os.path.isabs(img) and os.path.exists(img):
        return img
    page_path = page_abs_path(img)
    if os.path.exists(page_path):
        return page_path
    if os.path.exists(img):
        return img
    legacy = os.path.join("static", img)
    if os.path.exists(legacy):
        return legacy
    return img


# Function to encode the image
def encode_image(image_path):
  with open(image_path, "rb") as image_file:
    return base64.b64encode(image_file.read()).decode('utf-8')

def generate_response(images, query, session_id, resized_height=280, resized_width=280, model_choice='qwen', vlm_id=None):
    """
    Generates a response using the selected model based on the query and images.
    Returns: (response_text, used_images)
    """
    try:
        logger.info(f"Generating response using model '{model_choice}'.")
        
        # Convert resized_height and resized_width to integers
        resized_height = int(resized_height)
        resized_width = int(resized_width)
        
        full_image_paths = [_resolve_image_path(img) for img in images]
        valid_images = [img for img in full_image_paths if os.path.exists(img)]
        
        if not valid_images:
            logger.warning("No valid images found for analysis.")
            return "No images could be loaded for analysis.", []

        # If model only supports single image, use only the first image
        if is_single_image_model(model_choice):
            valid_images = [valid_images[0]]
            logger.info(f"Model {model_choice} only supports single image, using first image only.")

        if model_choice == 'qwen':
            # Cloud Qwen-VL via DashScope (OpenAI-compatible multimodal chat)
            client, model_name = load_model('qwen')
            model_name = vlm_id or model_name
            try:
                content = [{"type": "text", "text": query}]
                for img_path in valid_images:
                    logger.info(f"Processing image for DashScope: {img_path}")
                    if os.path.exists(img_path):
                        base64_image = encode_image(img_path)
                        # Guess mime from extension; default jpeg
                        ext = os.path.splitext(img_path)[1].lower().lstrip('.')
                        mime = {
                            'jpg': 'image/jpeg',
                            'jpeg': 'image/jpeg',
                            'png': 'image/png',
                            'webp': 'image/webp',
                            'gif': 'image/gif',
                        }.get(ext, 'image/jpeg')
                        content.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime};base64,{base64_image}"
                            }
                        })
                    else:
                        logger.warning(f"Image file not found: {img_path}")

                if len(content) == 1:
                    return "No images could be loaded for analysis.", []

                last_error = None
                for attempt in range(1, 4):
                    try:
                        response = client.chat.completions.create(
                            model=model_name,
                            messages=[{"role": "user", "content": content}],
                            max_tokens=1024,
                        )
                        generated_text = response.choices[0].message.content
                        logger.info(f"Response generated using DashScope model '{model_name}'.")
                        return generated_text, valid_images
                    except APIConnectionError as e:
                        last_error = e
                        logger.warning(
                            f"DashScope connection failed (attempt {attempt}/3): {e}"
                        )
                        time.sleep(1.5 * attempt)
                raise last_error
            except APIConnectionError as e:
                logger.error(f"Error in DashScope Qwen processing: {str(e)}", exc_info=True)
                return (
                    "无法连接阿里云 DashScope（通义千问）。本机代理可能已关闭或拒绝连接。"
                    "请确认能访问 https://dashscope.aliyuncs.com ，或关掉失效的 HTTP 代理后重试。",
                    [],
                )
            except Exception as e:
                logger.error(f"Error in DashScope Qwen processing: {str(e)}", exc_info=True)
                return f"An error occurred while processing the images: {str(e)}", []
        
        elif model_choice == 'gemini':
            model, _ = load_model('gemini')
            
            try:
                content = [query]  # Add the text query first
                
                for img_path in valid_images:
                    if os.path.exists(img_path):
                        try:
                            img = Image.open(img_path)
                            content.append(img)
                        except Exception as e:
                            logger.error(f"Error opening image {img_path}: {e}")
                    else:
                        logger.warning(f"Image file not found: {img_path}")
                
                if len(content) == 1:  # Only text, no images
                    return "No images could be loaded for analysis.", []
                
                response = model.generate_content(content)
                
                if response.text:
                    generated_text = response.text
                    logger.info("Response generated using Gemini model.")
                    return generated_text, valid_images
                else:
                    return "The Gemini model did not generate any text response.", []
            
            except Exception as e:
                logger.error(f"Error in Gemini processing: {str(e)}", exc_info=True)
                return f"An error occurred while processing the images: {str(e)}", []
        
        elif model_choice == 'gpt4':
            api_key = os.getenv("OPENAI_API_KEY")
            client = OpenAI(api_key=api_key)
            
            try:
                content = [{"type": "text", "text": query}]
                
                for img_path in valid_images:
                    logger.info(f"Processing image: {img_path}")
                    if os.path.exists(img_path):
                        base64_image = encode_image(img_path)
                        content.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        })
                    else:
                        logger.warning(f"Image file not found: {img_path}")
                
                if len(content) == 1:  # Only text, no images
                    return "No images could be loaded for analysis.", []
                
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {
                            "role": "user",
                            "content": content
                        }
                    ],
                    max_tokens=1024
                )
                
                generated_text = response.choices[0].message.content
                logger.info("Response generated using GPT-4 model.")
                return generated_text, valid_images
            
            except Exception as e:
                logger.error(f"Error in GPT-4 processing: {str(e)}", exc_info=True)
                return f"An error occurred while processing the images: {str(e)}", []
        
        elif model_choice == 'llama-vision':
            # Load model, processor, and device
            model, processor, device = load_model('llama-vision')

            # Process images
            # For simplicity, use the first image
            image_path = valid_images[0] if valid_images else None
            if image_path and os.path.exists(image_path):
                image = Image.open(image_path).convert('RGB')
            else:
                return "No valid image found for analysis.", []

            # Prepare messages
            messages = [
                {"role": "user", "content": [
                    {"type": "image"},
                    {"type": "text", "text": query}
                ]}
            ]
            input_text = processor.apply_chat_template(messages, add_generation_prompt=True)
            inputs = processor(image, input_text, return_tensors="pt").to(device)

            # Generate response
            output = model.generate(**inputs, max_new_tokens=512)
            response = processor.decode(output[0], skip_special_tokens=True)
            return response, valid_images
        
        elif model_choice == "pixtral":
            model, tokenizer, generate_func, device = load_model('pixtral')

            def image_to_data_url(image_path):
                with open(image_path, "rb") as image_file:
                    encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                ext = os.path.splitext(image_path)[1][1:]  # Get the file extension
                return f"data:image/{ext};base64,{encoded_string}"

            from mistral_common.protocol.instruct.messages import UserMessage, TextChunk, ImageURLChunk
            from mistral_common.protocol.instruct.request import ChatCompletionRequest

            # Prepare the content with text and images
            content = [TextChunk(text=query)]
            for img_path in valid_images[:1]:  # Use only the first image
                content.append(ImageURLChunk(image_url=image_to_data_url(img_path)))

            completion_request = ChatCompletionRequest(messages=[UserMessage(content=content)])

            encoded = tokenizer.encode_chat_completion(completion_request)

            images = encoded.images
            tokens = encoded.tokens

            out_tokens, _ = generate_func([tokens], model, images=[images], max_tokens=256, temperature=0.35, eos_id=tokenizer.instruct_tokenizer.tokenizer.eos_id)
            result = tokenizer.decode(out_tokens[0])

            logger.info("Response generated using Pixtral model.")
            return result, valid_images
        
        elif model_choice == "molmo":
            model, processor, device = load_model('molmo')
            model = model.half()  # Convert model to half precision
            pil_images = []
            for img_path in valid_images[:1]:  # Process only the first image for now
                if os.path.exists(img_path):
                    try:
                        img = Image.open(img_path).convert('RGB')
                        pil_images.append(img)
                    except Exception as e:
                        logger.error(f"Error opening image {img_path}: {e}")
                else:
                    logger.warning(f"Image file not found: {img_path}")

            if not pil_images:
                return "No images could be loaded for analysis.", []

            try:
                # Process the images and text
                inputs = processor.process(
                    images=pil_images,
                    text=query
                )

                # Move inputs to the correct device and make a batch of size 1
                # Convert float tensors to half precision, but keep integer tensors as they are
                inputs = {k: (v.to(device).unsqueeze(0).half() if v.dtype in [torch.float32, torch.float64] else 
                            v.to(device).unsqueeze(0))
                        if isinstance(v, torch.Tensor) else v 
                        for k, v in inputs.items()}

                # Generate output
                with torch.no_grad():  # Disable gradient calculation
                    output = model.generate_from_batch(
                        inputs,
                        GenerationConfig(max_new_tokens=200, stop_strings="<|endoftext|>"),
                        tokenizer=processor.tokenizer
                    )

                # Only get generated tokens; decode them to text
                generated_tokens = output[0, inputs['input_ids'].size(1):]
                generated_text = processor.tokenizer.decode(generated_tokens, skip_special_tokens=True)

                return generated_text, valid_images

            except Exception as e:
                logger.error(f"Error in Molmo processing: {str(e)}", exc_info=True)
                return f"An error occurred while processing the images: {str(e)}", []
            finally:
                # Close the opened images to free up resources
                for img in pil_images:
                    img.close()              
        elif model_choice == 'groq-llama-vision':
            client = load_model('groq-llama-vision')

            content = [{"type": "text", "text": query}]

            # Use only the first image
            if valid_images:
                img_path = valid_images[0]
                if os.path.exists(img_path):
                    base64_image = encode_image(img_path)
                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    })
                else:
                    logger.warning(f"Image file not found: {img_path}")

            if len(content) == 1:  # Only text, no images
                return "No images could be loaded for analysis.", []

            try:
                chat_completion = client.chat.completions.create(
                    messages=[
                        {
                            "role": "user",
                            "content": content
                        }
                    ],
                    model="llava-v1.5-7b-4096-preview",
                )
                generated_text = chat_completion.choices[0].message.content
                logger.info("Response generated using Groq Llama Vision model.")
                return generated_text, valid_images
            except Exception as e:
                logger.error(f"Error in Groq Llama Vision processing: {str(e)}", exc_info=True)
                return f"An error occurred while processing the image: {str(e)}", []
        elif model_choice == 'ollama-llama-vision':
            try:
                message = {
                    'role': 'user',
                    'content': query,
                    'images': [valid_images[0]]
                }
                
                response = ollama.chat(
                    model='llama3.2-vision',
                    messages=[message]
                )
                
                logger.info("Response generated using Ollama Llama Vision model.")
                return response['message']['content'], valid_images
                
            except Exception as e:
                logger.error(f"Error in Ollama Llama Vision processing: {str(e)}", exc_info=True)
                return f"An error occurred while processing the image: {str(e)}", []
        else:
            logger.error(f"Invalid model choice: {model_choice}")
            return "Invalid model selected.", []
    except Exception as e:
        logger.error(f"Error generating response: {e}")
        return f"An error occurred while generating the response: {str(e)}", []
