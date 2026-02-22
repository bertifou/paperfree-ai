import pytesseract
from PIL import Image
import PyPDF2
from openai import OpenAI
from database import SessionLocal, Setting

def get_llm_config():
    db = SessionLocal()
    base_url = db.query(Setting).filter(Setting.key == 'llm_base_url').first()
    api_key = db.query(Setting).filter(Setting.key == 'llm_api_key').first()
    model = db.query(Setting).filter(Setting.key == 'llm_model').first()
    db.close()

    return {
        'base_url': base_url.value if base_url else 'http://localhost:1234/v1',
        'api_key': api_key.value if api_key else 'lm-studio',
        'model': model.value if model else 'local-model'
    }

def process_document(file_path):
    # Extraction du texte
    text = ""
    if file_path.lower().endswith('.pdf'):
        with open(file_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                text += page.extract_text() + "\n"
    else:
        text = pytesseract.image_to_string(Image.open(file_path))

    # Analyse par LLM
    config = get_llm_config()
    try:
        client = OpenAI(base_url=config['base_url'], api_key=config['api_key'])
        response = client.chat.completions.create(
            model=config['model'],
            messages=[
                {"role": "system", "content": "Tu es un assistant spécialisé dans le tri de documents. Analyse le texte fourni et donne une catégorie courte (ex: Facture, Impôts, Santé, Travail) et un résumé de 10 mots maximum."},
                {"role": "user", "content": text[:2000]} # Limite pour éviter de saturer le contexte local
            ]
        )
        analysis = response.choices[0].message.content
    except Exception as e:
        analysis = f"Erreur d'analyse LLM: {str(e)}"

    return text, analysis
