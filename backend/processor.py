import pytesseract
from PIL import Image
from pypdf import PdfReader
import os
import requests
import json

def extract_text_from_pdf(pdf_path):
    reader = PdfReader(pdf_path)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
    return text

def extract_text_from_image(image_path):
    return pytesseract.image_to_string(Image.open(image_path))

def analyze_with_local_llm(text):
    # Tentative de connexion à Ollama (local)
    url = "http://localhost:11434/api/generate"
    prompt = f"Analyse ce texte de document et donne-moi uniquement le type de document (Facture, Contrat, Lettre, etc.) et le montant total si applicable en format JSON: {text[:1000]}"

    try:
        response = requests.post(url, json={
            "model": "llama3",
            "prompt": prompt,
            "stream": False
        })
        return response.json().get('response', 'Unknown')
    except:
        return "Local LLM not reachable"

def process_document(file_path):
    print(f"Processing: {file_path}")
    ext = os.path.splitext(file_path)[1].lower()

    text = ""
    if ext == '.pdf':
        text = extract_text_from_pdf(file_path)
    elif ext in ['.jpg', '.jpeg', '.png']:
        text = extract_text_from_image(file_path)

    analysis = analyze_with_local_llm(text)
    print(f"Analysis result: {analysis}")

    # Ici on sauvegarderait dans la DB SQLite
    return text, analysis
