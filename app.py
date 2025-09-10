from flask import Flask, redirect, request, session, url_for, render_template, make_response, jsonify, send_from_directory, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from sqlalchemy import inspect
from urllib.parse import urlencode
from datetime import datetime
from sqlalchemy import text
import requests
import os
import google.generativeai as genai
import logging
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import re
from datetime import datetime, timedelta
# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -----------------------
# CONFIGURATION APP
# -----------------------
app = Flask(__name__, static_folder='static')

# Ajoute ce code dans ton fichier app.py, après la création de l'app Flask

@app.context_processor
def inject_user_profile():
    """Injecte les informations du profil utilisateur dans tous les templates"""
    if 'profile' in session:
        profile = session['profile']
        
        # Récupérer les informations de l'utilisateur depuis la base de données
        user = None
        if profile.get('sub'):
            user = User.query.filter_by(sub=profile['sub']).first()
        
        return dict(
            picture=profile.get('picture', ''),
            name=profile.get('name', ''),
            first_name=profile.get('first_name', ''),
            last_name=profile.get('last_name', ''),
            email=profile.get('email', ''),
            language=profile.get('language', ''),
            country=profile.get('country', ''),
            email_verified=profile.get('email_verified', False),
            sub=profile.get('sub', ''),
            secteur=user.secteur if user and user.secteur else '',
            interets=user.interets if user and user.interets else []
        )
    
    return dict(
        picture='',
        name='',
        first_name='',
        last_name='',
        email='',
        language='',
        country='',
        email_verified=False,
        sub='',
        secteur='',
        interets=[]
    )
app.secret_key = os.urandom(24)
app.config['SESSION_COOKIE_NAME'] = 'linkedin_session'

# ✅ CONFIGURATION BASE DE DONNÉES
from urllib.parse import quote_plus

# Utilisation de la chaîne de connexion fournie par Render
db_url = os.getenv("DATABASE_URL")
if not db_url:
    # Fallback vers une connexion locale si la variable d'environnement n'est pas définie
    password = quote_plus("Lexia2025")
    db_url = f'postgresql://user3:{password}@localhost:5432/Boostdb'
    logger.info("Utilisation de la base de données locale")
else:
    # Pour Render, vérifier et corriger l'URL si nécessaire
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    logger.info("Utilisation de la base de données Render")

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# -----------------------
# MODÈLES SQLALCHEMY
# -----------------------
class LocalUser(db.Model):
    __tablename__ = 'local_users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    company = db.Column(db.String(120))
    job_title = db.Column(db.String(120))
    is_active = db.Column(db.Boolean, default=True)
    is_verified = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    login_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def is_locked(self):
        if self.locked_until:
            return datetime.utcnow() < self.locked_until
        return False
    
    def lock_account(self, minutes=15):
        self.locked_until = datetime.utcnow() + timedelta(minutes=minutes)
        db.session.commit()
    
    def unlock_account(self):
        self.login_attempts = 0
        self.locked_until = None
        db.session.commit()
    
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

# Fonctions utilitaires
def is_valid_email(email):
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def is_strong_password(password):
    """Vérifier que le mot de passe est suffisamment fort"""
    if len(password) < 8:
        return False, "Le mot de passe doit contenir au moins 8 caractères"
    
    if not re.search(r'[A-Z]', password):
        return False, "Le mot de passe doit contenir au moins une majuscule"
    
    if not re.search(r'[a-z]', password):
        return False, "Le mot de passe doit contenir au moins une minuscule"
    
    if not re.search(r'[0-9]', password):
        return False, "Le mot de passe doit contenir au moins un chiffre"
    
    if not re.search(r'[!@#$%^&*(),.?\":{}|<>]', password):
        return False, "Le mot de passe doit contenir au moins un caractère spécial"
    
    return True, "Mot de passe valide"

# Décorateur pour vérifier l'authentification
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('signin'))
        return f(*args, **kwargs)
    return decorated_function


class User(db.Model):
    __tablename__ = 'users'  # Nom explicite pour éviter les conflits avec mot-clé SQL
    id = db.Column(db.Integer, primary_key=True)
    sub = db.Column(db.String(128), unique=True, nullable=False)
    email = db.Column(db.String(120))
    name = db.Column(db.String(120))
    first_name = db.Column(db.String(80))
    last_name = db.Column(db.String(80))
    picture = db.Column(db.String(250))
    language = db.Column(db.String(10))
    country = db.Column(db.String(10))
    email_verified = db.Column(db.Boolean, default=False)
    secteur = db.Column(db.String(120))
    interets = db.Column(db.JSON, default=list)  # JSON au lieu de ARRAY
    posts = db.relationship('Post', backref='author', lazy=True)

class Post(db.Model):
    __tablename__ = 'posts'  # Nom explicite de la table
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text)
    published_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # Référence à users.id
    scheduled = db.Column(db.Boolean, default=False)
    linkedin_post_urn = db.Column(db.String(100))

# Fonction d'initialisation de la base de données
def create_default_admin():
    """Créer un utilisateur admin par défaut sur Render"""
    try:
        # Vérifier si un admin existe déjà
        admin_user = LocalUser.query.filter_by(email="admin@linkedboost.com").first()
        
        if not admin_user:
            admin_user = LocalUser(
                email="admin@linkedboost.com",
                first_name="Admin",
                last_name="LinkedBoost",
                company="LinkedBoost",
                job_title="Administrateur",
                is_verified=True
            )
            admin_user.set_password("AdminLinkedBoost2025!")
            
            db.session.add(admin_user)
            db.session.commit()
            
            logger.info("✅ Utilisateur admin créé sur Render")
            logger.info("📧 Email: admin@linkedboost.com")
            logger.info("🔐 Password: AdminLinkedBoost2025!")
        else:
            logger.info("ℹ️ Utilisateur admin déjà existant")
            
    except Exception as e:
        logger.error(f"❌ Erreur lors de la création de l'admin: {str(e)}")
        

def init_db():
    """Initialiser la base de données avec les tables nécessaires"""
    with app.app_context():
        try:
            # Vérifier les tables existantes avant la création
            inspector = inspect(db.engine)
            existing_tables = inspector.get_table_names()
            logger.info(f"Tables existantes avant création: {existing_tables}")
            
            # Créer les tables si elles n'existent pas
            db.create_all()
            logger.info("Tables créées ou vérifiées avec succès")
            
            # 🔥 NOUVEAU : Créer un utilisateur admin par défaut sur Render
            if os.getenv("RENDER"):
                create_default_admin()
            
            # Vérifier les tables après création
            existing_tables = inspector.get_table_names()
            logger.info(f"Tables existantes après création: {existing_tables}")
            
        except Exception as e:
            logger.error(f"Erreur lors de l'initialisation de la base de données: {str(e)}")
            raise

# Initialiser la base de données au démarrage
init_db()
# -----------------------
# LINKEDIN + GEMINI
# -----------------------
CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID", "86occjps58doir")
CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET", "WPL_AP1.C8C6uXjTbpJyQUx2.Y7COPg==")
REDIRECT_URI = os.getenv("LINKEDIN_REDIRECT_URI", "https://linkedinboost.onrender.com/callback")

LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
LINKEDIN_ASSET_REGISTRATION_URL = "https://api.linkedin.com/v2/assets?action=registerUpload"
LINKEDIN_POSTS_URL = "https://api.linkedin.com/v2/ugcPosts"

SCOPES = "openid email profile w_member_social"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyAH-hVzlQJQTCOLB1UsznxrObuY8XIsKMQ")
genai.configure(api_key=GEMINI_API_KEY)
import requests
import re
from datetime import datetime, timedelta

# Ajouter cette configuration près de vos autres constantes
NEWS_API_KEY = "2cc0499903c24433a7646123cb3a82e0"  # Remplacez par votre vraie clé
NEWS_API_URL = "https://newsapi.org/v2/everything"
# -----------------------
# ROUTES FLASK
# -----------------------
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "GRfBXoBp4ZxiaHejhH03WWpuSm07btLzWxyBq6Q9dnVFPr6BrJ8xpFlg")  # À remplacer par votre vraie clé
PEXELS_API_URL = "https://api.pexels.com/v1"

import json
import os
from datetime import datetime, timedelta

# Créer un dossier cache s'il n'existe pas
cache_dir = os.path.join(os.path.dirname(__file__), 'cache')
if not os.path.exists(cache_dir):
    os.makedirs(cache_dir)

from datetime import datetime
import html
import re
import requests

import tempfile
import os
from urllib.parse import urlparse

def search_pexels_photos(query, per_page=12, page=1):
    """
    Recherche de photos sur Pexels
    
    Args:
        query (str): Terme de recherche
        per_page (int): Nombre de photos par page (max 80)
        page (int): Numéro de page
        
    Returns:
        dict: Résultats de l'API Pexels ou None en cas d'erreur
    """
    if not PEXELS_API_KEY or PEXELS_API_KEY == "VOTRE_CLE_API_PEXELS":
        logger.warning("Clé API Pexels non configurée")
        return None
    
    headers = {
        "Authorization": PEXELS_API_KEY
    }
    
    params = {
        "query": query,
        "per_page": min(per_page, 80),  # Limite de l'API
        "page": page,
        "orientation": "landscape"  # Mieux pour LinkedIn
    }
    
    try:
        response = requests.get(f"{PEXELS_API_URL}/search", headers=headers, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            # Formater les résultats pour notre usage
            formatted_photos = []
            for photo in data.get('photos', []):
                formatted_photos.append({
                    'id': photo['id'],
                    'photographer': photo['photographer'],
                    'photographer_url': photo['photographer_url'],
                    'src': {
                        'small': photo['src']['small'],
                        'medium': photo['src']['medium'],
                        'large': photo['src']['large'],
                        'original': photo['src']['original']
                    },
                    'alt': photo['alt'],
                    'url': photo['url']
                })
            
            return {
                'photos': formatted_photos,
                'total_results': data.get('total_results', 0),
                'page': data.get('page', 1),
                'per_page': data.get('per_page', 12),
                'next_page': data.get('next_page', None)
            }
        else:
            logger.error(f"Erreur API Pexels: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"Exception lors de la recherche Pexels: {str(e)}")
        return None
        
def upload_pdf_to_linkedin(pdf_content, access_token, urn):
    """
    Upload un PDF sur LinkedIn en utilisant la nouvelle API Documents
    
    Args:
        pdf_content (bytes): Contenu du PDF
        access_token (str): Token d'accès LinkedIn
        urn (str): URN de l'utilisateur
        
    Returns:
        str: Document URN ou None en cas d'erreur
    """
    try:
        # 1. Étape 1 : Enregistrer le document pour upload
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
            "LinkedIn-Version": "202308"  # Version récente requise pour les documents
        }

        # Payload pour l'enregistrement du document
        register_payload = {
            "initializeUploadRequest": {
                "owner": urn
            }
        }

        # Nouvelle URL pour les documents
        register_url = "https://api.linkedin.com/rest/documents?action=initializeUpload"
        
        logger.info(f"📄 Enregistrement du document PDF...")
        reg_resp = requests.post(register_url, headers=headers, json=register_payload)
        
        if reg_resp.status_code != 200:
            logger.error(f"❌ Erreur enregistrement PDF: {reg_resp.status_code} - {reg_resp.text}")
            return None

        upload_info = reg_resp.json().get("value", {})
        upload_url = upload_info.get("uploadUrl")
        document_urn = upload_info.get("document")

        if not upload_url or not document_urn:
            logger.error("❌ Upload URL ou document URN manquant dans la réponse")
            logger.error(f"Réponse complète: {reg_resp.text}")
            return None

        logger.info(f"✅ Document enregistré: {document_urn}")
        logger.info(f"📤 URL d'upload: {upload_url}")

        # 2. Étape 2 : Upload du contenu PDF
        upload_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/pdf",
            "LinkedIn-Version": "202308"
        }

        logger.info(f"📤 Upload du contenu PDF ({len(pdf_content)} bytes)...")
        put_resp = requests.put(upload_url, data=pdf_content, headers=upload_headers)

        if put_resp.status_code not in [200, 201]:
            logger.error(f"❌ Erreur upload contenu PDF: {put_resp.status_code} - {put_resp.text}")
            return None

        logger.info(f"✅ PDF uploadé avec succès: {document_urn}")

        # 3. Étape 3 : Vérifier le statut du document
        check_url = f"https://api.linkedin.com/rest/documents/{document_urn.replace('urn:li:document:', '')}"
        check_resp = requests.get(check_url, headers=headers)
        
        if check_resp.status_code == 200:
            doc_info = check_resp.json()
            status = doc_info.get("status", "UNKNOWN")
            logger.info(f"📋 Statut du document: {status}")
            
            if status == "AVAILABLE":
                logger.info(f"✅ Document prêt pour publication")
                return document_urn
            elif status in ["PROCESSING", "WAITING_UPLOAD"]:
                logger.info(f"⏳ Document en cours de traitement, on continue...")
                return document_urn
            else:
                logger.warning(f"⚠️ Statut inattendu du document: {status}")
                return document_urn  # On tente quand même
        
        # Si la vérification échoue, on retourne quand même l'URN
        logger.warning(f"⚠️ Impossible de vérifier le statut, on continue avec: {document_urn}")
        return document_urn

    except Exception as e:
        logger.error(f"❌ Exception lors de l'upload PDF: {str(e)}")
        return None


# Correction dans la fonction publish - partie PDF
def handle_pdf_upload_in_publish(request, access_token, urn, media_assets, post_data):
    """
    Gère l'upload PDF dans la fonction publish
    """
    pdf_file = request.files.get("pdf_file")
    if pdf_file and pdf_file.filename.endswith(".pdf"):
        try:
            logger.info(f"📄 Traitement du PDF: {pdf_file.filename}")
            pdf_content = pdf_file.read()
            
            # Upload du PDF avec la fonction corrigée
            pdf_document_urn = upload_pdf_to_linkedin(pdf_content, access_token, urn)
            
            if pdf_document_urn:
                logger.info(f"✅ PDF uploadé avec succès: {pdf_document_urn}")
                
                # Structure correcte pour un document LinkedIn
                document_media = {
                    "status": "READY",
                    "document": pdf_document_urn,
                    "title": {
                        "text": pdf_file.filename
                    },
                    "description": {
                        "text": "Document partagé"
                    }
                }
                
                # Remplacer tous les médias par le document
                media_assets.clear()
                media_assets.append(document_media)
                
                # Modifier le shareMediaCategory pour DOCUMENT
                post_data["specificContent"]["com.linkedin.ugc.ShareContent"]["shareMediaCategory"] = "DOCUMENT"
                
                logger.info(f"📄 Configuration post pour document: {pdf_document_urn}")
                return True
            else:
                logger.error(f"❌ Échec de l'upload PDF")
                return False
                
        except Exception as e:
            logger.error(f"❌ Exception lors du traitement PDF: {str(e)}")
            return False
    
    return False

def upload_image_to_linkedin(image_content, access_token, urn, content_type='image/jpeg'):
    """
    Upload une image sur LinkedIn et retourne l'asset URN
    
    Args:
        image_content (bytes): Contenu de l'image
        access_token (str): Token d'accès LinkedIn
        urn (str): URN de l'utilisateur
        content_type (str): Type MIME de l'image
        
    Returns:
        str: Asset URN ou None en cas d'erreur
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0"
    }
    
    try:
        # 1. Enregistrer le média sur LinkedIn
        register_payload = {
            "registerUploadRequest": {
                "owner": urn,
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "serviceRelationships": [
                    {"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}
                ]
            }
        }

        reg_resp = requests.post(LINKEDIN_ASSET_REGISTRATION_URL, headers=headers, json=register_payload)
        if reg_resp.status_code != 200:
            logger.error(f"Erreur registre upload: {reg_resp.text}")
            return None

        upload_info = reg_resp.json().get("value", {})
        upload_url = upload_info.get("uploadMechanism", {}).get("com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest", {}).get("uploadUrl")
        asset = upload_info.get("asset")

        if not upload_url or not asset:
            logger.error("Upload URL ou asset manquant")
            return None

        # 2. Uploader l'image
        upload_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": content_type
        }

        put_resp = requests.put(upload_url, data=image_content, headers=upload_headers)

        if put_resp.status_code not in [200, 201]:
            logger.error(f"Erreur upload image: {put_resp.text}")
            return None

        return asset
        
    except Exception as e:
        logger.error(f"Exception upload image LinkedIn: {str(e)}")
        return None

def download_pexels_photo(photo_url, size='medium'):
    """
    Télécharge une photo depuis Pexels et la retourne en bytes
    
    Args:
        photo_url (str): URL de la photo
        size (str): Taille de l'image ('small', 'medium', 'large')
        
    Returns:
        bytes: Contenu de l'image ou None en cas d'erreur
    """
    try:
        response = requests.get(photo_url, timeout=30)
        if response.status_code == 200:
            return response.content
        else:
            logger.error(f"Erreur téléchargement photo: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Exception téléchargement photo: {str(e)}")
        return None

@app.route("/api/search_photos", methods=["POST"])
def search_photos():
    """
    API endpoint pour rechercher des photos Pexels
    """
    if 'profile' not in session:
        return jsonify({"error": "Non authentifié"}), 401
    
    try:
        data = request.get_json()
        query = data.get('query', '').strip()
        page = data.get('page', 1)
        
        if not query:
            return jsonify({"error": "Terme de recherche requis"}), 400
        
        if len(query) < 2:
            return jsonify({"error": "Terme de recherche trop court (minimum 2 caractères)"}), 400
        
        # Rechercher sur Pexels
        results = search_pexels_photos(query, per_page=12, page=page)
        
        if results is None:
            return jsonify({"error": "Service de photos temporairement indisponible"}), 503
        
        return jsonify({
            "success": True,
            "results": results
        })
        
    except Exception as e:
        logger.error(f"Erreur recherche photos: {str(e)}")
        return jsonify({"error": "Erreur interne du serveur"}), 500

# Si vous avez besoin d'une route personnalisée pour les fichiers statiques, 
# vous pouvez ajouter ceci (mais normalement ce n'est pas nécessaire):
@app.route('/static/<path:path>')
def send_static(path):
    return send_from_directory('static', path)

# Vous pouvez utiliser cette route pour déboguer
@app.route('/debug-static')
def debug_static():
    static_files = os.listdir('static')
    return f"Fichiers dans le dossier static: {static_files}"
@app.template_filter('clean_html')
def clean_html(text):
    """Nettoie le texte des tags HTML et entités"""
    if not text:
        return ""
    
    # Décodage des entités HTML
    text = html.unescape(text)
    
    # Suppression des balises HTML
    text = re.sub(r'<[^>]+>', '', text)
    
    # Nettoyage des espaces multiples
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text

def optimize_query_with_gemini(raw_query, language="fr"):
    """
    Agent hybride : utilise Gemini pour optimiser la requête avant l'envoi à NewsAPI.
    Corrige les fautes, reformule et génère plusieurs requêtes optimisées.
    
    Args:
        raw_query (str): Requête brute de l'utilisateur
        language (str): Langue de la requête
        
    Returns:
        list: Liste de requêtes optimisées
    """
    try:
        prompt = f"""
Tu es un expert en recherche d'actualités. Optimise cette requête pour l'API NewsAPI.

Requête utilisateur : "{raw_query}"
Langue : {language}

Tâches :
1. Corrige les fautes d'orthographe et de grammaire
2. Identifie les concepts clés et génère des synonymes pertinents
3. Crée 3-5 requêtes optimisées différentes pour maximiser la pertinence
4. Utilise des termes spécifiques et des variations intelligentes

Exemples de transformation :
- "IA" → "intelligence artificielle", "artificial intelligence", "AI"
- "tech" → "technologie", "innovation technologique", "startup tech"
- "crypto" → "cryptomonnaie", "bitcoin", "blockchain"

Format de réponse JSON uniquement :
{{
    "original_query": "requête originale",
    "corrected_query": "requête corrigée",
    "optimized_queries": [
        "requête optimisée 1",
        "requête optimisée 2",
        "requête optimisée 3"
    ],
    "reasoning": "explication de l'optimisation"
}}

Réponds uniquement en JSON valide.
"""

        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        
        # Extraire le JSON de la réponse
        response_text = response.text.strip()
        if response_text.startswith('```json'):
            response_text = response_text[7:-3]
        elif response_text.startswith('```'):
            response_text = response_text[3:-3]
            
        result = json.loads(response_text)
        
        logger.info(f"🤖 Gemini optimisation - Original: '{raw_query}' → Optimisé: {result['optimized_queries']}")
        
        return result['optimized_queries']
        
    except Exception as e:
        logger.error(f"❌ Erreur Gemini optimisation: {str(e)}")
        # Fallback : retourner la requête originale nettoyée
        return [raw_query.strip()]

def get_news_by_keyword(keyword, days=30, language="fr"):
    """
    Agent hybride : utilise Gemini pour optimiser les requêtes avant NewsAPI.
    Corrige les fautes, reformule et génère plusieurs requêtes pour maximiser la pertinence.

    Args:
        keyword (str): Mot-clé ou expression entrée par l'utilisateur
        days (int, optional): Nombre de jours pour les actualités récentes
        language (str, optional): Langue des articles (fr, en)

    Returns:
        list: Liste d'articles d'actualité optimisés
    """
    # Générer le nom du cache basé sur la requête originale
    cache_key = f"{keyword.strip().replace(' ', '_')}_{language}_{days}.json"
    cache_path = os.path.join(cache_dir, cache_key)

    # Vérifier si un cache valide existe (moins de 3 heures)
    if os.path.exists(cache_path):
        file_modified_time = os.path.getmtime(cache_path)
        now = datetime.now().timestamp()

        if now - file_modified_time < 10800:
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cached_data = json.load(f)
                    logger.info(f"✅ Cache utilisé pour : {keyword}")
                    return cached_data
            except Exception as e:
                logger.error(f"❌ Erreur de lecture du cache : {str(e)}")

    # 🚀 AGENT HYBRIDE : Optimiser avec Gemini
    optimized_queries = optimize_query_with_gemini(keyword, language)
    
    all_articles = []
    date_from = (datetime.utcnow() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    # Exécuter chaque requête optimisée
    for i, optimized_query in enumerate(optimized_queries):
        try:
            # Formater pour NewsAPI (espaces → +)
            formatted_query = '+'.join(optimized_query.split())
            
            params = {
                'q': formatted_query,
                'from': date_from,
                'sortBy': 'relevancy',
                'language': language,
                'apiKey': NEWS_API_KEY,
                'pageSize': 15  # Réduit pour éviter les doublons
            }

            logger.info(f"🔍 Requête {i+1}/{len(optimized_queries)} NewsAPI : {formatted_query}")

            response = requests.get(NEWS_API_URL, params=params, timeout=15)

            if response.status_code == 200:
                data = response.json()
                articles = data.get('articles', [])

                for article in articles:
                    if article.get('title') and article.get('description'):
                        # Éviter les doublons basés sur l'URL
                        if not any(existing.get('url') == article.get('url') for existing in all_articles):
                            try:
                                date_str = article.get('publishedAt', '')
                                date_obj = datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%SZ')
                                article['formatted_date'] = date_obj.strftime('%d/%m/%Y')
                                article['query_source'] = optimized_query  # Traçabilité
                            except:
                                article['formatted_date'] = 'Date inconnue'
                                article['query_source'] = optimized_query

                            all_articles.append(article)

            else:
                logger.warning(f"⚠️ Erreur API {response.status_code} pour requête '{optimized_query}'")

        except Exception as e:
            logger.error(f"❌ Erreur requête '{optimized_query}': {str(e)}")
            continue

    # Trier par date (plus récent en premier) et limiter à 21 articles
    all_articles.sort(key=lambda x: x.get('publishedAt', ''), reverse=True)
    final_articles = all_articles[:21]

    # Sauvegarder en cache
    if final_articles:
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(final_articles, f, ensure_ascii=False)
                logger.info(f"💾 Cache créé pour : {keyword} ({len(final_articles)} articles)")
        except Exception as e:
            logger.error(f"❌ Erreur d'écriture du cache : {str(e)}")

    logger.info(f"🎯 Agent hybride terminé : {len(final_articles)} articles trouvés via {len(optimized_queries)} requêtes optimisées")
    return final_articles
    
def get_cached_news(query, language, days=3):
    """
    Récupère les résultats mis en cache ou effectue un nouvel appel API
    
    Args:
        query (str): Requête de recherche
        language (str): Langue des articles
        days (int): Jours à considérer
        
    Returns:
        list: Liste d'articles
    """
    # Générer un nom de fichier de cache basé sur la requête
    cache_filename = f"{query.replace(' ', '_')}_{language}_{days}.json"
    cache_path = os.path.join(cache_dir, cache_filename)
    
    # Vérifier si un cache valide existe (moins de 3 heures)
    if os.path.exists(cache_path):
        file_modified_time = os.path.getmtime(cache_path)
        now = datetime.now().timestamp()
        
        # Si le cache a moins de 3 heures
        if now - file_modified_time < 10800:  # 3 heures en secondes
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cached_data = json.load(f)
                    print(f"Utilisation du cache pour: {query}")
                    return cached_data
            except Exception as e:
                print(f"Erreur de lecture du cache: {str(e)}")
    
    # Si pas de cache valide, faire l'appel à l'API
    articles = get_news_by_sector_actual(query, days=days, language=language)
    
    # Sauvegarder les résultats dans le cache
    try:
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(articles, f, ensure_ascii=False)
            print(f"Cache créé pour: {query}")
    except Exception as e:
        print(f"Erreur d'écriture du cache: {str(e)}")
    
    return articles

def get_news_by_sector(sector, keywords=None, days=7, language="fr"):
    """
    Version améliorée pour récupérer plus d'actualités par secteur
    """
    # Vérifier le cache
    cache_key = f"sector_{sector}_{language}_{days}.json"
    cache_path = os.path.join(cache_dir, cache_key)
    
    # Vérifier si un cache valide existe (moins de 1 heure pour avoir plus de fraîcheur)
    if os.path.exists(cache_path):
        file_modified_time = os.path.getmtime(cache_path)
        now = datetime.now().timestamp()
        
        if now - file_modified_time < 3600:  # 1 heure en secondes
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cached_data = json.load(f)
                    logger.info(f"Utilisation du cache secteur pour: {sector}")
                    return cached_data
            except Exception as e:
                logger.error(f"Erreur de lecture du cache secteur: {str(e)}")
    
    # Mapping étendu avec plus de termes de recherche
    sector_keywords = {
        'tech': [
            'technologie OR informatique OR "intelligence artificielle" OR IA OR digital',
            'startup OR innovation OR développement OR logiciel OR application',
            'cybersécurité OR blockchain OR cloud OR "réalité virtuelle"',
            'automation OR robotique OR "machine learning" OR algorithme'
        ],
        'marketing': [
            'marketing OR publicité OR "réseaux sociaux" OR communication',
            'brand OR marque OR "content marketing" OR SEO',
            'influencer OR "marketing digital" OR e-commerce OR conversion',
            '"growth hacking" OR analytics OR "customer experience"'
        ],
        'finance': [
            'finance OR banque OR investissement OR économie OR bourse',
            'fintech OR crypto OR bitcoin OR "monnaie numérique"',
            'assurance OR crédit OR "gestion patrimoine" OR épargne',
            'régulation OR "marché financier" OR trading OR "taux intérêt"'
        ],
        'sante': [
            'santé OR médecine OR "bien-être" OR médical OR hôpital',
            'pharma OR médicament OR vaccin OR traitement OR thérapie',
            '"santé mentale" OR nutrition OR prévention OR diagnostic',
            'biotechnologie OR "recherche médicale" OR "santé digitale"'
        ],
        'education': [
            'éducation OR enseignement OR formation OR école OR université',
            '"formation professionnelle" OR "e-learning" OR pédagogie',
            'étudiant OR professeur OR "système éducatif" OR apprentissage',
            '"compétences numériques" OR "formation continue" OR diplôme'
        ],
        'rh': [
            '"ressources humaines" OR recrutement OR emploi OR "gestion talent"',
            'management OR leadership OR "bien-être travail" OR motivation',
            '"télétravail" OR "travail hybride" OR "qualité vie travail"',
            'formation OR "développement personnel" OR carrière OR "soft skills"'
        ],
        'consulting': [
            'conseil OR consulting OR stratégie OR "transformation digitale"',
            'management OR "amélioration performance" OR optimisation',
            '"change management" OR innovation OR "business model"',
            'audit OR "due diligence" OR "gestion projet" OR efficacité'
        ],
        'retail': [
            'commerce OR distribution OR retail OR vente OR "expérience client"',
            'e-commerce OR "commerce en ligne" OR marketplace OR omnicanal',
            'consommation OR "comportement consommateur" OR tendances',
            '"magasin connecté" OR "retail tech" OR "point vente" OR CRM'
        ],
        'general': [
            'entreprise OR business OR économie OR "actualité business"',
            'innovation OR startup OR "transformation numérique"',
            'management OR leadership OR "monde travail"',
            'France OR "marché français" OR "économie française"'
        ]
    }
    
    # Récupérer les termes de recherche pour le secteur
    search_terms = sector_keywords.get(sector, sector_keywords['general'])
    
    all_articles = []
    
    # Faire plusieurs requêtes avec différents termes pour avoir plus de variété
    for search_term in search_terms:
        try:
            # Ajouter des mots-clés supplémentaires si fournis
            if keywords:
                search_query = f"({search_term}) AND ({keywords})"
            else:
                search_query = search_term
            
            # Préparer les paramètres pour l'API
            date_from = (datetime.utcnow() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            params = {
                'q': search_query,
                'from': date_from,
                'sortBy': 'publishedAt',
                'language': language,
                'apiKey': NEWS_API_KEY,
                'pageSize': 25  # Moins par requête mais plus de requêtes
            }
            
            logger.info(f"Requête NewsAPI secteur {sector}: {search_query}")
            
            # Appel à l'API
            response = requests.get(NEWS_API_URL, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                articles = data.get('articles', [])
                
                # Filtrer et formater les articles
                for article in articles:
                    if article.get('title') and article.get('description'):
                        # Éviter les doublons
                        if not any(existing['url'] == article.get('url') for existing in all_articles):
                            try:
                                # Formater la date
                                date_str = article.get('publishedAt', '')
                                if date_str:
                                    date_obj = datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%SZ')
                                    article['formatted_date'] = date_obj.strftime('%d/%m/%Y')
                                else:
                                    article['formatted_date'] = 'Date inconnue'
                            except:
                                article['formatted_date'] = 'Date inconnue'
                            
                            all_articles.append(article)
                
                logger.info(f"Articles trouvés pour '{search_term}': {len(articles)}")
                
            else:
                logger.warning(f"Erreur API pour '{search_term}': {response.status_code}")
                
            # Petite pause entre les requêtes pour éviter les limites
            time.sleep(0.5)
            
        except Exception as e:
            logger.error(f"Erreur lors de la recherche '{search_term}': {str(e)}")
            continue
    
    # Trier par date et prendre les plus récents
    all_articles.sort(key=lambda x: x.get('publishedAt', ''), reverse=True)
    
    # Limiter à 20 articles maximum pour de meilleures performances
    final_articles = all_articles[:20]
    
    logger.info(f"Total articles secteur {sector}: {len(final_articles)}")
    
    # Sauvegarder les résultats dans le cache
    try:
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(final_articles, f, ensure_ascii=False)
            logger.info(f"Cache secteur créé pour: {sector}")
    except Exception as e:
        logger.error(f"Erreur d'écriture du cache secteur: {str(e)}")
    
    return final_articles

@app.route("/test-news")
def test_news():
    """Route de test pour débugger les actualités"""
    try:
        # Test avec une requête simple
        test_articles = get_news_by_sector_actual("tech", "intelligence artificielle", days=7, language="fr")
        
        html_debug = f"""
        <h1>🔍 Test News API - Debug</h1>
        <h2>Résultats trouvés: {len(test_articles)}</h2>
        
        <h3>📊 Informations de debug:</h3>
        <ul>
            <li><strong>Clé API:</strong> {NEWS_API_KEY[:15]}...</li>
            <li><strong>URL API:</strong> {NEWS_API_URL}</li>
            <li><strong>Secteur testé:</strong> tech</li>
            <li><strong>Mot-clé:</strong> intelligence artificielle</li>
        </ul>
        
        <h3>📰 Articles trouvés:</h3>
        """
        
        for i, article in enumerate(test_articles[:5]):
            html_debug += f"""
            <div style="border: 1px solid #ccc; padding: 15px; margin: 10px 0; border-radius: 8px;">
                <h4>{i+1}. {article.get('title', 'No title')}</h4>
                <p><strong>Source:</strong> {article.get('source', {}).get('name', 'Unknown')}</p>
                <p><strong>Description:</strong> {article.get('description', 'No description')[:200]}...</p>
                <p><strong>Date:</strong> {article.get('formatted_date', 'Unknown')}</p>
                <p><strong>URL:</strong> <a href="{article.get('url', '#')}" target="_blank">Lire l'article</a></p>
            </div>
            """
        
        if not test_articles:
            html_debug += """
            <div style="background: #fee; padding: 20px; border-radius: 8px; margin: 20px 0;">
                <h3>❌ Aucun article trouvé</h3>
                <p>Causes possibles:</p>
                <ul>
                    <li>Clé API NewsAPI expirée ou invalide</li>
                    <li>Limite de requêtes atteinte (429)</li>
                    <li>Aucun article disponible pour ces critères</li>
                    <li>Problème de connexion réseau</li>
                </ul>
                <p><strong>Action recommandée:</strong> Vérifiez les logs serveur pour plus de détails.</p>
            </div>
            """
        
        html_debug += '<p><a href="/news_assistant">← Retour aux actualités</a></p>'
        return html_debug
        
    except Exception as e:
        return f"""
        <h1>❌ Erreur lors du test News API</h1>
        <div style="background: #fee; padding: 20px; border-radius: 8px;">
            <h3>Erreur détectée:</h3>
            <p><strong>{str(e)}</strong></p>
            
            <h3>Actions à effectuer:</h3>
            <ol>
                <li>Vérifiez votre clé API NewsAPI sur <a href="https://newsapi.org/account" target="_blank">newsapi.org</a></li>
                <li>Assurez-vous que la clé est bien définie dans vos variables d'environnement</li>
                <li>Vérifiez que vous n'avez pas dépassé la limite de 100 requêtes/jour (plan gratuit)</li>
                <li>Essayez avec d'autres mots-clés plus simples</li>
            </ol>
        </div>
        <p><a href="/news_assistant">← Retour aux actualités</a></p>
        """

@app.route("/search_linkedin_users", methods=["POST"])
def search_linkedin_users():
    """
    API endpoint pour rechercher des utilisateurs LinkedIn
    """
    if 'profile' not in session or 'access_token' not in session:
        return jsonify({"error": "Non authentifié"}), 401
    
    access_token = session['access_token']
    query = request.json.get('query', '')
    
    if not query or len(query) < 2:
        return jsonify({"error": "La requête doit contenir au moins 2 caractères"}), 400
    
    # URL de l'API LinkedIn pour la recherche de personnes
    # Note: Cette API nécessite une autorisation spéciale de LinkedIn
    search_url = "https://api.linkedin.com/v2/search/blended"
    
    params = {
        "q": "keywork",
        "keywords": query,
        "filters": "List(resultType->PEOPLE)",
        "limit": 5
    }
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Restli-Protocol-Version": "2.0.0"
    }
    
    try:
        response = requests.get(search_url, params=params, headers=headers)
        
        if response.status_code != 200:
            # L'API de recherche LinkedIn est très restrictive
            # Si elle échoue, nous utilisons une méthode alternative
            return search_linkedin_users_alternative(query)
        
        data = response.json()
        results = []
        
        for element in data.get('elements', []):
            if element.get('type') == 'PEOPLE':
                for person in element.get('elements', []):
                    person_id = person.get('entityUrn', '').split(':')[-1]
                    results.append({
                        'id': person_id,
                        'name': person.get('title', {}).get('text', ''),
                        'headline': person.get('headline', {}).get('text', ''),
                        'profile_url': f"https://www.linkedin.com/in/{person_id}/",
                        'image_url': person.get('image', {}).get('attributes', [{}])[0].get('sourceImage', {}).get('accessibilityText', '')
                    })
        
        return jsonify({"results": results})
    
    except Exception as e:
        logger.error(f"Erreur lors de la recherche LinkedIn: {str(e)}")
        return search_linkedin_users_alternative(query)

def search_linkedin_users_alternative(query):
    """
    Méthode alternative pour suggérer des utilisateurs LinkedIn
    Cette fonction génère toujours au moins une suggestion
    """
    results = []
    
    try:
        # Chercher dans la base de données des utilisateurs qui correspondent à la requête
        users = User.query.filter(
            (User.name.ilike(f"%{query}%")) | 
            (User.first_name.ilike(f"%{query}%")) | 
            (User.last_name.ilike(f"%{query}%"))
        ).limit(5).all()
        
        for user in users:
            # Extraire l'ID LinkedIn à partir du sub
            linkedin_id = user.sub.split('_')[-1] if user.sub else None
            
            if linkedin_id:
                results.append({
                    'id': linkedin_id,
                    'name': f"{user.first_name} {user.last_name}",
                    'headline': "Utilisateur LinkedBoost",
                    'profile_url': f"https://www.linkedin.com/in/{linkedin_id}/",
                    'image_url': user.picture or ""
                })
    except Exception as e:
        logger.error(f"Erreur lors de la recherche d'utilisateurs: {str(e)}")
    
    # Si aucun résultat, ajouter des suggestions génériques
    # TOUJOURS ajouter au moins une suggestion pour tester
    if len(results) == 0:
        # Ajouter quelques suggestions génériques
        results.append({
            'id': 'test-user',
            'name': query if query else 'Utilisateur test',
            'headline': "Test de mention LinkedIn",
            'profile_url': f"https://www.linkedin.com/search/results/people/?keywords={query}",
            'image_url': ""
        })
        
        # Ajouter quelques célébrités LinkedIn comme suggestions
        celebrities = [
            {
                'id': 'billgates',
                'name': 'Bill Gates',
                'headline': 'Co-fondateur de Microsoft',
                'profile_url': 'https://www.linkedin.com/in/williamhgates/',
                'image_url': ''
            },
            {
                'id': 'melindagates',
                'name': 'Melinda French Gates',
                'headline': 'Philanthrope',
                'profile_url': 'https://www.linkedin.com/in/melindagates/',
                'image_url': ''
            }
        ]
        
        # Ajouter ces célébrités aux résultats
        results.extend(celebrities)
    
    return jsonify({"results": results})


# Modifications à apporter dans app.py

@app.route("/news_assistant", methods=["GET", "POST"])
def news_assistant():
    if 'profile' not in session:
        return redirect(url_for("index"))
    
    # Récupérer l'utilisateur
    user = User.query.filter_by(sub=session['profile'].get("sub", "")).first()
    if not user:
        return redirect(url_for("dashboard"))
    
    # Récupérer le secteur de l'utilisateur ou utiliser une valeur par défaut
    sector = user.secteur or "general"
    news_articles = []
    selected_article = None
    error_message = None
    success_message = None
    
    # Récupérer les paramètres de recherche
    search_keyword = request.args.get('keyword', '')
    language = request.args.get('language', 'fr')
    
    # Traitement des actions POST
    if request.method == "POST":
        logger.info(f"POST reçu avec données: {request.form}")
        
        if 'search' in request.form:
            # Recherche d'actualités avec un mot-clé
            search_keyword = request.form.get('keyword', '')
            language = request.form.get('language', 'fr')
            
            # Rediriger vers GET avec les paramètres pour permettre le partage d'URL
            return redirect(url_for('news_assistant', keyword=search_keyword, language=language))
            
        elif 'select_article' in request.form:
            # L'utilisateur a sélectionné un article
            try:
                logger.info("Traitement de la sélection d'article")
                
                # Récupérer les données directement depuis le formulaire
                article_data = {
                    'title': request.form.get('article_title', ''),
                    'description': request.form.get('article_description', ''),
                    'source': {'name': request.form.get('article_source', '')},
                    'url': request.form.get('article_url', ''),
                    'formatted_date': request.form.get('article_date', ''),
                    'urlToImage': request.form.get('article_image', ''),
                    'customPrompt': request.form.get('custom_prompt', ''),
                    'tone': request.form.get('tone', 'professionnel'),
                    'perspective': request.form.get('perspective', 'neutre')
                }
                
                logger.info(f"Données article récupérées: {article_data}")
                
                # Vérifier que l'article a un titre et une description
                if not article_data['title'] or not article_data['description']:
                    error_message = "L'article sélectionné est incomplet. Veuillez réessayer."
                    logger.error("Article incomplet détecté")
                else:
                    # Stocker l'article dans la session
                    session['selected_article'] = article_data
                    logger.info("Article stocké dans la session avec succès")
                    
                    # Rediriger vers le dashboard avec un paramètre de succès
                    session['article_success'] = True
                    return redirect(url_for("dashboard"))
                    
            except Exception as e:
                error_message = f"Erreur lors de la sélection de l'article: {str(e)}"
                logger.error(f"Erreur de sélection d'article: {str(e)}")
    
    # Pour les requêtes GET ou si POST n'a pas redirigé
    try:
        # Récupérer les actualités avec gestion d'erreurs améliorée
        logger.info(f"Recherche d'actualités: secteur={sector}, keyword={search_keyword}, langue={language}")
        
        if search_keyword:
            # Si l'utilisateur a entré un mot-clé, effectuer une recherche générale (ignorer le secteur)
            news_articles = get_news_by_keyword(search_keyword, language=language, days=30)
        else:
            # Sinon, afficher les actualités du secteur de l'utilisateur
            news_articles = get_news_by_sector(sector, language=language, days=30)
        
        # Log du nombre d'articles trouvés
        logger.info(f"Nombre d'articles trouvés: {len(news_articles)}")
        
        # Si aucun article n'est trouvé, faire une recherche de secours
        if not news_articles:
            if search_keyword:
                logger.info(f"Aucun article trouvé avec mot-clé, tentative avec secteur général")
                news_articles = get_news_by_sector("general", search_keyword, language=language, days=30)
            else:
                logger.info(f"Aucun article trouvé pour le secteur, tentative avec le secteur 'general'")
                news_articles = get_news_by_sector("general", language=language, days=30)
        
    except Exception as e:
        error_message = f"Erreur lors de la récupération des actualités: {str(e)}"
        logger.error(f"Exception lors de la récupération des actualités: {str(e)}")
        news_articles = []
    
    # Récupérer l'article sélectionné depuis la session si disponible
    if not selected_article and 'selected_article' in session:
        selected_article = session.get('selected_article')
    
    return render_template(
        "news_assistant.html",
        news=news_articles,
        selected=selected_article,
        sector=sector,
        keyword=search_keyword,
        language=language,
        error=error_message,
        success=success_message
    )

    
@app.route("/")
def index():
    # Si déjà connecté, rediriger vers LinkedIn
    if 'user_id' in session:
        return redirect(url_for('linkedin_auth'))
    
    return render_template("index_auth.html")

@app.route("/signin", methods=["GET", "POST"])
def signin():
    if 'user_id' in session:
        return redirect(url_for('linkedin_auth'))
    
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        
        if not email or not password:
            return render_template("signin.html", error="Veuillez remplir tous les champs")
        
        if not is_valid_email(email):
            return render_template("signin.html", error="Format d'email invalide")
        
        # Rechercher l'utilisateur
        user = LocalUser.query.filter_by(email=email).first()
        
        if not user:
            return render_template("signin.html", error="Email ou mot de passe incorrect")
        
        # Vérifier si le compte est verrouillé
        if user.is_locked():
            minutes_left = int((user.locked_until - datetime.utcnow()).total_seconds() / 60)
            return render_template("signin.html", error=f"Compte verrouillé. Réessayez dans {minutes_left} minutes")
        
        # Vérifier le mot de passe
        if not user.check_password(password):
            # Incrémenter les tentatives échouées
            user.login_attempts += 1
            if user.login_attempts >= 5:
                user.lock_account()
                db.session.commit()
                return render_template("signin.html", error="Trop de tentatives échouées. Compte verrouillé pour 15 minutes")
            else:
                db.session.commit()
                return render_template("signin.html", error="Email ou mot de passe incorrect")
        
        # Connexion réussie
        user.login_attempts = 0
        user.last_login = datetime.utcnow()
        user.locked_until = None
        db.session.commit()
        
        session['user_id'] = user.id
        session['user_email'] = user.email
        session['user_name'] = user.full_name
        
        logger.info(f"Connexion réussie pour: {email}")
        return redirect(url_for('linkedin_auth'))
    
    return render_template("signin.html")

# Route Sign Up (Inscription)
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if 'user_id' in session:
        return redirect(url_for('linkedin_auth'))
    
    if request.method == "POST":
        # Récupérer les données du formulaire
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        company = request.form.get("company", "").strip()
        job_title = request.form.get("job_title", "").strip()
        
        # Validations
        if not all([email, password, confirm_password, first_name, last_name]):
            return render_template("signup.html", error="Veuillez remplir tous les champs obligatoires")
        
        if not is_valid_email(email):
            return render_template("signup.html", error="Format d'email invalide")
        
        if password != confirm_password:
            return render_template("signup.html", error="Les mots de passe ne correspondent pas")
        
        is_valid, password_message = is_strong_password(password)
        if not is_valid:
            return render_template("signup.html", error=password_message)
        
        # Vérifier si l'email existe déjà
        if LocalUser.query.filter_by(email=email).first():
            return render_template("signup.html", error="Un compte avec cet email existe déjà")
        
        try:
            # Créer le nouveau utilisateur
            user = LocalUser(
                email=email,
                first_name=first_name,
                last_name=last_name,
                company=company,
                job_title=job_title
            )
            user.set_password(password)
            
            db.session.add(user)
            db.session.commit()
            
            # Connexion automatique après inscription
            session['user_id'] = user.id
            session['user_email'] = user.email
            session['user_name'] = user.full_name
            
            logger.info(f"Nouveau compte créé: {email}")
            return redirect(url_for('welcome'))
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erreur lors de la création du compte: {str(e)}")
            return render_template("signup.html", error="Erreur lors de la création du compte")
    
    return render_template("signup.html")

# Route de bienvenue après inscription
@app.route("/welcome")
@login_required
def welcome():
    user_id = session.get('user_id')
    user = LocalUser.query.get(user_id)
    return render_template("welcome.html", user=user)

# Route vers LinkedIn (protégée)
@app.route("/linkedin_auth")
@login_required
def linkedin_auth():
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": "random123",
        "prompt": "login"
    }
    auth_url = f"{LINKEDIN_AUTH_URL}?{urlencode(params)}"
    return redirect(auth_url)


@app.route("/api/check_email", methods=["POST"])
def check_email():
    email = request.json.get('email', '').strip().lower()
    
    if not is_valid_email(email):
        return jsonify({'available': False, 'message': 'Format d\'email invalide'})
    
    user = LocalUser.query.filter_by(email=email).first()
    if user:
        return jsonify({'available': False, 'message': 'Cet email est déjà utilisé'})
    
    return jsonify({'available': True, 'message': 'Email disponible'})

# Route de profil utilisateur
@app.route("/profile")
@login_required
def profile():
    user_id = session.get('user_id')
    user = LocalUser.query.get(user_id)
    return render_template("user_profile.html", user=user)

# Route pour mettre à jour le profil
@app.route("/profile/update", methods=["POST"])
@login_required
def update_profile():
    user_id = session.get('user_id')
    user = LocalUser.query.get(user_id)
    
    user.first_name = request.form.get("first_name", "").strip()
    user.last_name = request.form.get("last_name", "").strip()
    user.company = request.form.get("company", "").strip()
    user.job_title = request.form.get("job_title", "").strip()
    
    try:
        db.session.commit()
        session['user_name'] = user.full_name
        return redirect(url_for('profile'))
    except Exception as e:
        db.session.rollback()
        return render_template("user_profile.html", user=user, error="Erreur lors de la mise à jour")

# Route de déconnexion
@app.route("/logout")
def logout():
    user_email = session.get('user_email')
    session.clear()
    
    if user_email:
        logger.info(f"Déconnexion de: {user_email}")
    
    resp = make_response(redirect("/"))
    resp.set_cookie('linkedin_session', '', expires=0)
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

# Route mot de passe oublié
@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        
        if not email or not is_valid_email(email):
            return render_template("forgot_password.html", error="Veuillez entrer une adresse email valide")
        
        user = LocalUser.query.filter_by(email=email).first()
        if user:
            # En production, vous enverriez un email ici
            logger.info(f"Demande de réinitialisation de mot de passe pour: {email}")
            return render_template("forgot_password.html", success="Si cet email existe, vous recevrez les instructions de réinitialisation")
        else:
            # Ne pas révéler si l'email existe ou non
            return render_template("forgot_password.html", success="Si cet email existe, vous recevrez les instructions de réinitialisation")
    
    return render_template("forgot_password.html")


@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "Erreur : aucun code fourni par LinkedIn."

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    
    try:
        token_resp = requests.post(LINKEDIN_TOKEN_URL, data=data, headers=headers)

        if token_resp.status_code != 200:
            return f"Erreur token: {token_resp.text}"

        access_token = token_resp.json().get("access_token")
        session['access_token'] = access_token
        headers = {"Authorization": f"Bearer {access_token}"}

        userinfo_resp = requests.get(LINKEDIN_USERINFO_URL, headers=headers)
        if userinfo_resp.status_code != 200:
            return f"Erreur lors de la récupération du profil : {userinfo_resp.text}"

        userinfo = userinfo_resp.json()
        session['profile'] = {
            'email': userinfo.get("email", "inconnu"),
            'name': userinfo.get("name", ""),
            'first_name': userinfo.get("given_name", ""),
            'last_name': userinfo.get("family_name", ""),
            'picture': userinfo.get("picture", ""),
            'language': userinfo.get("locale", {}).get("language", ""),
            'country': userinfo.get("locale", {}).get("country", ""),
            'email_verified': userinfo.get("email_verified", False),
            'sub': userinfo.get("sub", "")
        }

        # 🔁 Création ou mise à jour de l'utilisateur en base
        profile = session["profile"]
        
        # Debug pour voir le contenu du profile
        logger.info(f"Profile reçu: {profile}")
        
        try:
            # Vérifier si l'utilisateur existe déjà
            user = User.query.filter_by(sub=profile["sub"]).first()
            if not user:
                # Créer un nouvel utilisateur
                user = User(sub=profile["sub"])
                db.session.add(user)
                logger.info(f"Nouvel utilisateur créé avec sub: {profile['sub']}")

            # Mettre à jour les informations de l'utilisateur
            user.email = profile["email"]
            user.name = profile["name"]
            user.first_name = profile["first_name"]
            user.last_name = profile["last_name"]
            user.picture = profile["picture"]
            user.language = profile["language"]
            user.country = profile["country"]
            user.email_verified = profile["email_verified"]

            # Sauvegarder en base de données
            db.session.commit()
            logger.info(f"Utilisateur {user.id} mis à jour avec succès")
            
        except IntegrityError as e:
            db.session.rollback()
            logger.error(f"Erreur d'intégrité lors de la création/mise à jour de l'utilisateur: {str(e)}")
            return f"Erreur de base de données (IntegrityError): {str(e)}"
        except Exception as e:
            db.session.rollback()
            logger.error(f"Exception lors de la création/mise à jour de l'utilisateur: {str(e)}")
            return f"Erreur inattendue: {str(e)}"

        return redirect(url_for("dashboard"))
        
    except Exception as e:
        logger.error(f"Exception dans la route /callback: {str(e)}")
        return f"Erreur inattendue: {str(e)}"

# Modification à apporter à la route dashboard dans app.py
# Ajouter ce code à votre app.py pour créer un filtre personnalisé qui extrait les hashtags

import re

@app.template_filter('findhashtags')
def find_hashtags(text):
    """Extraire les hashtags d'un texte"""
    if not text:
        return []
    # Pattern pour trouver les hashtags
    hashtag_pattern = r'#(\w+)'
    hashtags = re.findall(hashtag_pattern, text)
    return ['#' + tag for tag in hashtags]

@app.route("/select_article", methods=["POST"])
def select_article():
    """Route simplifiée pour sélection directe d'articles"""
    if 'profile' not in session:
        return jsonify({'error': 'Non authentifié'}), 401
    
    try:
        # Récupérer les données JSON de l'article
        article_data = request.get_json()
        
        if not article_data:
            return jsonify({'error': 'Aucune donnée reçue'}), 400
        
        logger.info(f"Article sélectionné: {article_data.get('title', 'Sans titre')}")
        
        # Valider les données minimales
        if not article_data.get('title') or not article_data.get('description'):
            return jsonify({'error': 'Données d\'article incomplètes'}), 400
        
        # Stocker les données basiques dans la session
        session['selected_article'] = {
            'title': article_data.get('title', ''),
            'description': article_data.get('description', ''),
            'source': article_data.get('source', {}),
            'url': article_data.get('url', ''),
            'formatted_date': article_data.get('formatted_date', ''),
            'urlToImage': article_data.get('urlToImage', '')
        }
        session['article_success'] = True
        
        logger.info("Article stocké avec succès dans la session")
        
        return jsonify({
            'success': True,
            'message': 'Article sélectionné avec succès',
            'redirect': url_for('dashboard')
        })
        
    except Exception as e:
        logger.error(f"Erreur lors de la sélection: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route("/debug_articles")
def debug_articles():
    """Route de débogage pour tester le système d'articles"""
    if 'profile' not in session:
        return "Non connecté - <a href='/'>Se connecter</a>"
    
    debug_info = {
        'session_keys': list(session.keys()),
        'selected_article_exists': 'selected_article' in session,
        'selected_article_data': session.get('selected_article', 'Aucun'),
        'article_success': session.get('article_success', False),
        'profile_sub': session.get('profile', {}).get('sub', 'Non défini')
    }
    
    # Test de création d'un article factice
    test_article = {
        'title': 'Article de test - Intelligence Artificielle',
        'description': 'Ceci est un article de test pour vérifier le système de sélection d\'articles.',
        'source': {'name': 'Test Source'},
        'url': 'https://example.com/test-article',
        'formatted_date': '01/01/2025',
        'urlToImage': ''
    }
    
    # Si on ajoute ?set_test=1 à l'URL, on met l'article de test en session
    if request.args.get('set_test') == '1':
        session['selected_article'] = test_article
        session['article_success'] = True
        debug_info['test_article_set'] = True
    
    # Si on ajoute ?clear=1 à l'URL, on efface tout
    if request.args.get('clear') == '1':
        session.pop('selected_article', None)
        session.pop('article_success', None)
        debug_info['session_cleared'] = True
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head><title>Debug Articles</title></head>
    <body style="font-family: Arial; margin: 20px;">
        <h1>🔍 Debug Articles</h1>
        <pre>{debug_info}</pre>
        <p>
            <a href="?set_test=1" style="margin: 5px; padding: 8px; background: green; color: white; text-decoration: none;">Test Article</a>
            <a href="?clear=1" style="margin: 5px; padding: 8px; background: red; color: white; text-decoration: none;">Clear Session</a>
            <a href="/dashboard" style="margin: 5px; padding: 8px; background: blue; color: white; text-decoration: none;">Dashboard</a>
            <a href="/news_assistant" style="margin: 5px; padding: 8px; background: purple; color: white; text-decoration: none;">News</a>
        </p>
    </body>
    </html>
    """

@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if 'profile' not in session:
        return redirect(url_for("index"))

    draft = ""
    
    # Récupérer le message de succès de l'article
    article_success = session.pop('article_success', None)
    
    # Ajouter cette ligne pour gérer le bouton Annuler
    if request.args.get('clear') == 'true':
        # Supprimer l'article sélectionné de la session
        if 'selected_article' in session:
            session.pop('selected_article', None)
        return redirect(url_for('dashboard'))
    
    selected_article = session.get('selected_article')  # Récupérer l'article sélectionné
    
    # Récupérer l'utilisateur
    user = User.query.filter_by(sub=session['profile'].get("sub", "")).first()
    
    # Statistiques pour le tableau de bord
    scheduled_posts = 0
    if user:
        # Nombre de posts programmés
        now = datetime.utcnow()
        scheduled_posts = Post.query.filter_by(user_id=user.id, scheduled=True).filter(Post.published_at > now).count()
  
    # Récupérer les actualités tendance pour le secteur de l'utilisateur
    trending_news = []
    if user and user.secteur:
        try:
            # Récupérer 3 articles récents maximum
            trending_news = get_news_by_sector(user.secteur, days=1)[:3]
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des actualités: {str(e)}")
    
    if request.method == "POST":
        prompt = request.form.get("prompt")
        tone = request.form.get("tone", "professionnel")
        
        # Vérifier si l'utilisateur veut générer un post basé sur un article sélectionné
        if 'generate_from_article' in request.form and selected_article:
            try:
                logger.info("Génération de post à partir de l'article sélectionné")
                
                # NOUVEAU: Récupérer le prompt personnalisé depuis le formulaire
                custom_instructions = request.form.get("custom_instructions", "").strip()
                perspective = request.form.get("perspective", "neutre")
                format_type = request.form.get("format", "standard")
                
                # Adapter le prompt selon le format choisi
                format_instructions = {
                    "standard": "Rédige un post classique donnant ton analyse sur ce sujet",
                    "question": "Rédige un post sous forme de question engageante pour susciter des réactions",
                    "listpoints": "Rédige un post présentant les points clés ou enseignements principaux",
                    "story": "Rédige un post sous forme d'histoire ou de narration engageante"
                }
                
                format_text = format_instructions.get(format_type, format_instructions["standard"])
                
                # Générer le contenu avec Gemini
                model = genai.GenerativeModel("gemini-2.0-flash")
                
                # Construire le prompt avec les instructions personnalisées
                article_prompt = f"""
                Tu es un expert LinkedIn reconnu pour tes posts pertinents et percutants.
                
                Rédige un post LinkedIn complet à partir de l'article suivant :
                
                📰 **Titre** : {selected_article.get('title')}
                📄 **Résumé** : {selected_article.get('description')}
                🏢 **Source** : {selected_article.get('source', {}).get('name')}
                
                🎯 **Objectif** : Réagir à cette actualité en apportant :
                - une analyse personnelle,
                - un point de vue argumenté,
                - des implications concrètes pour ton secteur : {user.secteur if user and user.secteur else "général"},
                - des insights ou propositions utiles pour les professionnels.
                
                🗣️ **Style attendu** :
                - Ton : {tone}
                - Perspective : {perspective}
                - Format : {format_text}
                - Écriture fluide, humaine, professionnelle et engageante
                - Inclus une conclusion forte ou une ouverture pour discussion
                - Ajoute 2 ou 3 hashtags pertinents à la fin
                
                📝 **Contraintes** :
                - Maximum 900 caractères
                - Pas de lien externe
                - Commence directement par une accroche ou une idée forte
                - Parle à la première personne ("je") si le ton est personnel
                
                Inspire-toi des posts qui génèrent le plus de commentaires sur LinkedIn. Structure le contenu comme un mini-point de vue publié par un professionnel engagé.
                """

                
                # NOUVEAU: Ajouter les instructions personnalisées si elles existent
                if custom_instructions:
                    article_prompt += f"\n\nInstructions supplémentaires spécifiques: {custom_instructions}"
                
                response = model.generate_content(article_prompt)
                draft = response.text.strip()
                
                # Effacer l'article de la session après génération
                session.pop('selected_article', None)
                logger.info("Post généré avec succès à partir de l'article avec prompt personnalisé")
                
            except Exception as e:
                draft = f"Erreur Gemini : {str(e)}"
                logger.error(f"Erreur lors de la génération du post: {str(e)}")
        else:
            # Génération standard basée sur un prompt optimisé LinkedIn
            try:
                model = genai.GenerativeModel("gemini-2.0-flash")
                
                # Récupérer les intérêts et secteur de l'utilisateur
                interets = user.interets if user and user.interets else []
                secteur = user.secteur if user and user.secteur else "général"
                
                # Construction du prompt selon le ton choisi
                if tone == "personnel":
                    tone_instruction = f"""
- **Ton personnel** : Partage une expérience vécue ou une réflexion personnelle
- Base-toi sur ton secteur d'activité : {secteur}
- Intègre naturellement tes centres d'intérêt : {', '.join(interets) if interets else 'développement professionnel'}
- Utilise "je", "mon expérience", "j'ai appris"
- Raconte une anecdote ou un apprentissage personnel"""
                
                elif tone == "professionnel":
                    tone_instruction = """
- **Ton professionnel** : Démontre ton expertise et ta crédibilité
- Utilise un vocabulaire technique et précis
- Adopte une approche analytique et factuelle
- Partage des insights métier et des bonnes pratiques
- Position d'expert qui apporte de la valeur"""
                
                elif tone == "inspirant":
                    tone_instruction = """
- **Ton inspirant** : Motive et encourage ton audience
- Utilise des mots positifs et énergiques
- Partage une vision d'avenir ou des possibilités
- Encourage l'action et le dépassement de soi
- Ton optimiste qui donne envie d'agir"""
                
                else:  # conversationnel
                    tone_instruction = """
- **Ton conversationnel** : Crée une discussion détendue
- Utilise un langage courant et accessible
- Pose des questions directes à ton audience
- Adopte un style familier mais professionnel
- Comme si tu parlais à un collègue"""
                
                # Prompt principal optimisé LinkedIn
                optimized_prompt = f"""
Tu es un créateur de contenu LinkedIn expert. Rédige un post viral sur : "{prompt}"

🎯 **STRUCTURE OBLIGATOIRE** :
1. **Hook** (1-2 lignes) : Accroche qui arrête le scroll
2. **Corps** (3-5 paragraphes courts) : Développement avec sauts de ligne
3. **CTA** (1 ligne) : Question qui pousse à commenter
4. **Hashtags** (3-4) : Pertinents et populaires

📝 **CONSIGNES DE RÉDACTION** :
{tone_instruction}

✅ **RÈGLES LINKEDIN** :
- Longueur : 800-1300 caractères maximum
- Paragraphes de 1-2 lignes avec espaces
- Émojis stratégiques (2-3 max)
- Aucun lien externe
- Style authentique et humain
- Évite le jargon marketing

🚀 **OBJECTIF** : Maximiser engagement (likes, commentaires, partages)

Commence directement par l'accroche, sans titre ni introduction.
"""
                
                response = model.generate_content(optimized_prompt)
                draft = response.text.strip()
                
            except Exception as e:
                draft = f"Erreur Gemini : {str(e)}"
                logger.error(f"Erreur lors de la génération standard: {str(e)}")

    session['draft'] = draft
    
    # Passer les variables supplémentaires au template
    return render_template(
        "dashboard.html", 
        **session['profile'], 
        draft=draft,
        scheduled_posts=scheduled_posts,
        posts=user.posts if user else [],
        selected_article=selected_article,
        article_success=article_success
    )

# Import nécessaire pour les pauses entre requêtes
import time
def cleanup_old_cache_files():
    """Nettoie les fichiers de cache anciens pour libérer l'espace"""
    try:
        if not os.path.exists(cache_dir):
            return
        
        now = datetime.now().timestamp()
        one_day_ago = now - 86400  # 24 heures
        
        for filename in os.listdir(cache_dir):
            file_path = os.path.join(cache_dir, filename)
            if os.path.isfile(file_path):
                file_modified_time = os.path.getmtime(file_path)
                if file_modified_time < one_day_ago:
                    os.remove(file_path)
                    logger.info(f"Cache nettoyé: {filename}")
    
    except Exception as e:
        logger.error(f"Erreur lors du nettoyage du cache: {str(e)}")

# Appeler le nettoyage au démarrage de l'application
cleanup_old_cache_files()

def process_mentions_for_linkedin(content):
    """
    Convertit les mentions du format @[Nom](URL) au format LinkedIn
    pour l'API de publication LinkedIn
    
    Args:
        content (str): Contenu du post avec mentions
        
    Returns:
        tuple: (Texte formaté pour LinkedIn, Entités de mention pour l'API)
    """
    import re
    
    # Regex pour détecter les mentions
    mention_pattern = r'@\[(.*?)\]\((.*?)\)'
    mentions = re.findall(mention_pattern, content)
    
    # Si pas de mentions, retourner le contenu tel quel
    if not mentions:
        return content, []
    
    # Préparer les entités LinkedIn
    mention_entities = []
    
    # Pour chaque mention, créer une entité LinkedIn
    for i, (name, url) in enumerate(mentions):
        # Extraire l'ID LinkedIn de l'URL
        linkedin_id = url.rstrip('/').split('/')[-1]
        
        # Créer une entité de mention pour l'API LinkedIn
        mention_entity = {
            "entity": f"urn:li:person:{linkedin_id}",
            "textRange": {
                "start": 0,  # Sera mis à jour plus tard
                "length": len(f"@{name}")
            }
        }
        
        mention_entities.append(mention_entity)
    
    # Remplacer les mentions par leur format textuel simple (@Nom)
    processed_content = content
    start_offset = 0
    
    for i, (name, url) in enumerate(mentions):
        mention_format = f"@[{name}]({url})"
        simple_format = f"@{name}"
        
        # Trouver la position actuelle dans le texte traité
        pos = processed_content.find(mention_format)
        if pos != -1:
            # Mettre à jour la position de début pour l'API LinkedIn
            mention_entities[i]["textRange"]["start"] = pos + start_offset
            
            # Remplacer la mention par sa version simple
            processed_content = processed_content.replace(mention_format, simple_format, 1)
            
            # Mettre à jour le décalage pour les prochaines mentions
            start_offset += len(simple_format) - len(mention_format)
    
    return processed_content, mention_entities
    
@app.route("/publish", methods=["POST"])
def publish():
    access_token = session.get("access_token")
    if not access_token:
        return redirect(url_for("index"))

    content = request.form.get("post_content")
    date_str = request.form.get("publish_time")
    action = request.form.get("action")

    if not content:
        return "Aucun contenu reçu."

    try:
        publish_time = datetime.strptime(date_str, "%Y-%m-%dT%H:%M")
    except (ValueError, TypeError):
        publish_time = datetime.utcnow()

    now = datetime.utcnow()
    min_schedule_time = now + timedelta(minutes=30)

    profile = session.get('profile')
    sub = profile.get("sub", "")
    user_id = sub.split("_")[-1]
    urn = f"urn:li:person:{user_id}"
    user = User.query.filter_by(sub=sub).first()

    editing_post_id = session.get('editing_post_id')
    post_to_edit = Post.query.filter_by(id=editing_post_id, user_id=user.id).first() if editing_post_id else None

    if action == "save_draft":
        if post_to_edit:
            post_to_edit.content = content
            post_to_edit.published_at = now
            post_to_edit.scheduled = False
            post_to_edit.linkedin_post_urn = None
            db.session.commit()
        else:
            draft_post = Post(content=content, published_at=now, user_id=user.id, scheduled=False)
            db.session.add(draft_post)
            db.session.commit()

        session.pop('draft', None)
        session.pop('editing_post_id', None)
        return redirect(url_for("historique"))

    if action == "schedule":
        if publish_time < min_schedule_time:
            return "La date de programmation doit être au moins 30 minutes dans le futur. <a href='/dashboard'>Retour</a>"

        if post_to_edit:
            post_to_edit.content = content
            post_to_edit.published_at = publish_time
            post_to_edit.scheduled = True
            post_to_edit.linkedin_post_urn = None
            db.session.commit()
        else:
            planned_post = Post(content=content, published_at=publish_time, user_id=user.id, scheduled=True)
            db.session.add(planned_post)
            db.session.commit()

        session.pop('draft', None)
        session.pop('editing_post_id', None)
        return redirect(url_for("historique"))

    if action == "publish_now":
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0"
        }
        processed_content, mention_entities = process_mentions_for_linkedin(content)
        media_assets = []

        # 1. D'ABORD : Vérifier s'il y a un PDF (priorité absolue)
        pdf_file = request.files.get("pdf_file")
        has_pdf = pdf_file and pdf_file.filename.endswith(".pdf")
        
        if has_pdf:
            try:
                logger.info(f"📄 Traitement du PDF: {pdf_file.filename}")
                pdf_content = pdf_file.read()
                
                # Upload du PDF avec la nouvelle fonction
                pdf_document_urn = upload_pdf_to_linkedin(pdf_content, access_token, urn)
                
                if pdf_document_urn:
                    # Structure pour document LinkedIn
                    document_media = {
                        "status": "READY",
                        "document": pdf_document_urn,
                        "title": {
                            "text": pdf_file.filename
                        },
                        "description": {
                            "text": "Document partagé"
                        }
                    }
                    
                    media_assets = [document_media]  # SEUL le PDF
                    share_media_category = "DOCUMENT"
                    
                    logger.info(f"✅ PDF configuré pour publication: {pdf_document_urn}")
                else:
                    logger.error(f"❌ Échec de l'upload PDF")
                    return f"<h2>❌ Erreur lors de l'upload du PDF</h2><p><a href='/dashboard'>Retour</a></p>"
                    
            except Exception as e:
                logger.error(f"❌ Exception lors du traitement PDF: {str(e)}")
                return f"<h2>❌ Erreur PDF: {str(e)}</h2><p><a href='/dashboard'>Retour</a></p>"
        
        else:
            # 2. SINON : Traiter les images (si pas de PDF)
            
            # Images locales
            uploaded_files = request.files.getlist("images[]")
            max_images = min(len(uploaded_files), 9)
            for i in range(max_images):
                file = uploaded_files[i]
                if file and file.filename:
                    try:
                        asset = upload_image_to_linkedin(file.read(), access_token, urn, file.content_type)
                        if asset:
                            media_assets.append({
                                "status": "READY",
                                "media": asset,
                                "description": {"text": f"Image {i+1}"}
                            })
                            logger.info(f"Image locale {i+1} uploadée avec succès: {asset}")
                    except Exception as e:
                        logger.error(f"Exception lors de l'upload de l'image locale {i+1}: {str(e)}")

            # Photos Pexels
            pexels_photos = request.form.getlist("pexels_photos[]")
            for i, photo_data in enumerate(pexels_photos):
                if len(media_assets) >= 9:
                    break
                try:
                    photo_info = json.loads(photo_data)
                    photo_url = photo_info.get('src', {}).get('large', '')
                    if photo_url:
                        image_content = download_pexels_photo(photo_url)
                        if image_content:
                            asset = upload_image_to_linkedin(image_content, access_token, urn, 'image/jpeg')
                            if asset:
                                media_assets.append({
                                    "status": "READY",
                                    "media": asset,
                                    "description": {"text": f"Photo by {photo_info.get('photographer', 'Pexels')}"}
                                })
                                logger.info(f"Photo Pexels {i+1} uploadée avec succès: {asset}")
                except Exception as e:
                    logger.error(f"Exception lors de l'upload de la photo Pexels {i+1}: {str(e)}")

            share_media_category = "IMAGE" if media_assets else "NONE"

        # 3. Créer le post avec la bonne catégorie
        post_data = {
            "author": urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": processed_content},
                    "shareMediaCategory": share_media_category,
                    "media": media_assets
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            }
        }

        if mention_entities:
            post_data["specificContent"]["com.linkedin.ugc.ShareContent"]["mentions"] = mention_entities

        # 4. Publication
        logger.info(f"📤 Publication avec {share_media_category}: {len(media_assets)} média(s)")
        logger.info(f"📤 Données post: {json.dumps(post_data, indent=2)}")
        
        post_resp = requests.post(LINKEDIN_POSTS_URL, headers=headers, json=post_data)
        
        if post_resp.status_code == 201:
            linkedin_urn = post_resp.json().get("id")
            logger.info(f"✅ Post publié avec succès: {linkedin_urn}")

            if post_to_edit:
                post_to_edit.content = content
                post_to_edit.published_at = now
                post_to_edit.scheduled = False
                post_to_edit.linkedin_post_urn = linkedin_urn
                db.session.commit()
            else:
                published_post = Post(content=content, published_at=now, user_id=user.id, scheduled=False, linkedin_post_urn=linkedin_urn)
                db.session.add(published_post)
                db.session.commit()

            session.pop('draft', None)
            session.pop('editing_post_id', None)
            return redirect(url_for("historique"))
        else:
            logger.error(f"❌ Erreur publication: {post_resp.status_code} - {post_resp.text}")
            return f"<h2>❌ Erreur lors de la publication :</h2><pre>{post_resp.text}</pre><p><a href='/dashboard'>Retour</a></p>"

            
@app.route("/edit_post/<int:post_id>", methods=["GET", "POST"])
def edit_post(post_id):
    if 'profile' not in session:
        return redirect(url_for("index"))

    # Récupérer l'utilisateur et le post
    user = User.query.filter_by(sub=session['profile'].get("sub", "")).first()
    if not user:
        flash("Utilisateur introuvable", "error")
        return redirect(url_for("historique"))

    post = Post.query.filter_by(id=post_id, user_id=user.id).first()
    if not post:
        flash("Post introuvable ou vous n'avez pas les droits", "error")
        return redirect(url_for("historique"))

    # Traitement POST
    if request.method == "POST":
        # DEBUG COMPLET des données reçues
        logger.info(f"🔍 === DEBUG EDIT POST {post_id} ===")
        logger.info(f"📋 request.method: {request.method}")
        logger.info(f"📋 request.form: {dict(request.form)}")
        logger.info(f"📋 request.files: {dict(request.files)}")
        
        try:
            # Récupérer les données du formulaire avec debug
            new_content = request.form.get("post_content", "").strip()
            new_date_str = request.form.get("publish_time", "")
            action = request.form.get("action", "AUCUNE_ACTION_DETECTEE")
            
            logger.info(f"📝 Contenu: {len(new_content)} caractères")
            logger.info(f"📅 Date: {new_date_str}")
            logger.info(f"🎯 ACTION DETECTEE: '{action}'")
            
            # Validation du contenu
            if not new_content:
                logger.warning("❌ Contenu vide détecté")
                flash("Le contenu du post ne peut pas être vide", "error")
                return render_template("edit_post.html", 
                                     post=post, 
                                     formatted_date=post.published_at.strftime("%Y-%m-%dT%H:%M") if post.published_at else "",
                                     **session.get('profile', {}))
            
            # Traitement de la date
            publish_time = None
            if new_date_str:
                try:
                    publish_time = datetime.strptime(new_date_str, "%Y-%m-%dT%H:%M")
                    logger.info(f"📅 Date parsée: {publish_time}")
                except (ValueError, TypeError) as e:
                    logger.error(f"❌ Erreur parsing date: {e}")
                    publish_time = datetime.utcnow()
            else:
                publish_time = datetime.utcnow()
                logger.info(f"📅 Date par défaut: {publish_time}")
            
            # Sauvegarder l'état AVANT modification
            old_scheduled = post.scheduled
            old_urn = post.linkedin_post_urn
            old_date = post.published_at
            
            logger.info(f"📊 AVANT: scheduled={old_scheduled}, urn={'OUI' if old_urn else 'NON'}, date={old_date}")
            
            # Mettre à jour le contenu
            post.content = new_content
            
            # TRAITEMENT DES ACTIONS avec debug ultra-détaillé
            if action == "save_draft":
                logger.info("🔄 TRAITEMENT ACTION: save_draft")
                post.scheduled = False
                post.published_at = datetime.utcnow()
                post.linkedin_post_urn = None
                logger.info(f"📝 Post {post_id} → BROUILLON: scheduled=False, urn=None")
                flash("Post sauvegardé en brouillon avec succès", "success")
                
            elif action == "schedule":
                logger.info("🔄 TRAITEMENT ACTION: schedule")
                now = datetime.utcnow()
                min_schedule_time = now + timedelta(minutes=30)
                
                logger.info(f"⏰ Vérification date: {publish_time} vs {min_schedule_time}")
                
                if publish_time < min_schedule_time:
                    logger.warning(f"❌ Date trop proche: {publish_time} < {min_schedule_time}")
                    flash("La date de programmation doit être au moins 30 minutes dans le futur", "error")
                    return render_template("edit_post.html", 
                                         post=post, 
                                         formatted_date=new_date_str,
                                         **session.get('profile', {}))
                
                post.scheduled = True
                post.published_at = publish_time
                post.linkedin_post_urn = None
                logger.info(f"⏰ Post {post_id} → PROGRAMMÉ: scheduled=True, date={publish_time}, urn=None")
                flash(f"Post programmé pour le {publish_time.strftime('%d/%m/%Y à %H:%M')}", "success")
                
            elif action == "publish_now":
                logger.info("🔄 TRAITEMENT ACTION: publish_now")
                access_token = session.get("access_token")
                if not access_token:
                    logger.error("❌ Aucun token d'accès LinkedIn")
                    flash("Token LinkedIn expiré. Veuillez vous reconnecter", "error")
                    return redirect(url_for("linkedin_auth"))
                
                # Tenter la publication sur LinkedIn
                logger.info("🚀 Tentative de publication sur LinkedIn...")
                
                profile = session.get('profile')
                sub = profile.get("sub", "")
                user_id = sub.split("_")[-1] if "_" in sub else sub.replace("urn:li:person:", "")
                urn = f"urn:li:person:{user_id}"
                
                logger.info(f"📤 URN utilisateur: {urn}")
                
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                    "X-Restli-Protocol-Version": "2.0.0"
                }
                
                # Publication simple sans images pour déboguer
                post_data = {
                    "author": urn,
                    "lifecycleState": "PUBLISHED",
                    "specificContent": {
                        "com.linkedin.ugc.ShareContent": {
                            "shareCommentary": {"text": new_content},
                            "shareMediaCategory": "NONE",
                            "media": []
                        }
                    },
                    "visibility": {
                        "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
                    }
                }
                
                logger.info(f"📤 Données post: {json.dumps(post_data, indent=2)}")
                
                try:
                    post_resp = requests.post(LINKEDIN_POSTS_URL, headers=headers, json=post_data, timeout=30)
                    logger.info(f"📤 Réponse LinkedIn: {post_resp.status_code}")
                    logger.info(f"📤 Contenu réponse: {post_resp.text}")
                    
                    if post_resp.status_code == 201:
                        linkedin_urn = post_resp.json().get("id")
                        post.linkedin_post_urn = linkedin_urn
                        post.scheduled = False
                        post.published_at = datetime.utcnow()
                        logger.info(f"✅ Post {post_id} → PUBLIÉ: urn={linkedin_urn}")
                        flash("Post publié avec succès sur LinkedIn !", "success")
                    else:
                        logger.error(f"❌ Erreur publication LinkedIn: {post_resp.status_code} - {post_resp.text}")
                        flash(f"Erreur LinkedIn ({post_resp.status_code}). Réessayez plus tard.", "error")
                        return render_template("edit_post.html", 
                                             post=post, 
                                             formatted_date=new_date_str,
                                             **session.get('profile', {}))
                
                except requests.exceptions.RequestException as e:
                    logger.error(f"❌ Exception réseau LinkedIn: {str(e)}")
                    flash("Erreur de connexion avec LinkedIn. Vérifiez votre connexion internet.", "error")
                    return render_template("edit_post.html", 
                                         post=post, 
                                         formatted_date=new_date_str,
                                         **session.get('profile', {}))
            else:
                logger.error(f"❌ ACTION INCONNUE: '{action}'")
                flash(f"Action inconnue: {action}", "error")
                return render_template("edit_post.html", 
                                     post=post, 
                                     formatted_date=new_date_str,
                                     **session.get('profile', {}))
            
            # Sauvegarder l'état APRÈS modification
            logger.info(f"📊 APRÈS: scheduled={post.scheduled}, urn={'OUI' if post.linkedin_post_urn else 'NON'}, date={post.published_at}")
            
            # SAUVEGARDE FORCÉE
            try:
                logger.info("💾 Début sauvegarde en base...")
                db.session.flush()
                db.session.commit()
                logger.info(f"✅ Post {post_id} sauvegardé avec succès")
                
                # Vérification post-sauvegarde
                db.session.refresh(post)
                logger.info(f"🔍 VÉRIFICATION: scheduled={post.scheduled}, urn={'OUI' if post.linkedin_post_urn else 'NON'}")
                
            except Exception as db_error:
                db.session.rollback()
                logger.error(f"❌ Erreur base de données: {str(db_error)}")
                flash("Erreur de sauvegarde en base de données", "error")
                return render_template("edit_post.html", 
                                     post=post, 
                                     formatted_date=new_date_str,
                                     **session.get('profile', {}))
            
            # Nettoyer la session
            session.pop('draft', None)
            session.pop('editing_post_id', None)
            
            logger.info(f"🎯 REDIRECT vers historique pour voir le résultat")
            
            # Redirection
            return redirect(url_for("historique"))
                
        except Exception as e:
            db.session.rollback()
            logger.error(f"❌ Erreur générale modification post {post_id}: {str(e)}")
            logger.error(f"❌ Traceback: {traceback.format_exc()}")
            flash("Une erreur inattendue est survenue", "error")
    
    # Affichage en GET
    formatted_date = post.published_at.strftime("%Y-%m-%dT%H:%M") if post.published_at else ""
    
    session['draft'] = post.content
    session['editing_post_id'] = post.id
    
    return render_template(
        "edit_post.html", 
        post=post, 
        formatted_date=formatted_date, 
        draft=post.content,
        **session.get('profile', {})
    )

# Route de test pour déboguer les données de formulaire
@app.route("/test_form_data", methods=["POST"])
def test_form_data():
    """Route de test pour voir exactement ce qui est envoyé par le formulaire"""
    logger.info("🧪 === TEST FORM DATA ===")
    logger.info(f"📋 request.method: {request.method}")
    logger.info(f"📋 request.form: {dict(request.form)}")
    logger.info(f"📋 request.files: {dict(request.files)}")
    logger.info(f"📋 request.json: {request.json}")
    logger.info(f"📋 request.data: {request.data}")
    
    return f"""
    <h1>Test Form Data</h1>
    <p>Method: {request.method}</p>
    <p>Form: {dict(request.form)}</p>
    <p>Files: {dict(request.files)}</p>
    <p><a href="javascript:history.back()">← Retour</a></p>
    """
    
@app.route("/delete_post/<int:post_id>")
def delete_post(post_id):
    if 'profile' not in session:
        return redirect(url_for("index"))

    user = User.query.filter_by(sub=session['profile'].get("sub", "")).first()
    if not user:
        flash("Utilisateur introuvable", "error")
        return redirect(url_for("historique"))

    post = Post.query.filter_by(id=post_id, user_id=user.id).first()
    if not post:
        flash("Post introuvable ou vous n'avez pas les droits", "error")
        return redirect(url_for("historique"))

    try:
        db.session.delete(post)
        db.session.commit()
        flash("Post supprimé avec succès", "success")
        logger.info(f"Post {post_id} supprimé par l'utilisateur {user.id}")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors de la suppression du post {post_id}: {str(e)}")
        flash("Erreur lors de la suppression du post", "error")

    return redirect(url_for("historique"))

@app.route("/profil", methods=["GET", "POST"])
def profil():
    if 'profile' not in session:
        return redirect(url_for("index"))

    profile = session['profile']
    user = User.query.filter_by(sub=profile.get("sub", "")).first()

    if request.method == "POST":
        secteur = request.form.get("secteur")
        interets = request.form.getlist("interets")

        if user:
            user.secteur = secteur
            user.interets = interets
            db.session.commit()

        profile['secteur'] = secteur
        profile['interets'] = interets
        session['profile'] = profile

    else:
        if user:
            profile['secteur'] = user.secteur
            profile['interets'] = user.interets or []
            session['profile'] = profile

    return render_template("profil.html", user=session['profile'])

@app.route("/historique")
def historique():
    if 'profile' not in session:
        return redirect(url_for("index"))

    sub = session["profile"].get("sub", "")
    user = User.query.filter_by(sub=sub).first()

    if not user:
        return "<p>Utilisateur introuvable en base.</p>"

    # Force refresh de la session SQLAlchemy
    db.session.expire_all()
    
    now = datetime.utcnow()
    posts = Post.query.filter_by(user_id=user.id).order_by(Post.published_at.desc()).all()
    
    logger.info(f"🔍 === DEBUG HISTORIQUE utilisateur {user.id} ===")
    logger.info(f"📊 Total posts: {len(posts)}")
    logger.info(f"🕐 Heure actuelle: {now}")
    
    # Classification avec debug ultra-détaillé
    published_posts = []
    scheduled_posts = []
    draft_posts = []
    
    for post in posts:
        has_urn = bool(post.linkedin_post_urn)
        is_scheduled = bool(post.scheduled)
        future_date = post.published_at and post.published_at > now
        
        logger.info(f"📄 Post {post.id}:")
        logger.info(f"   ├─ scheduled: {is_scheduled}")
        logger.info(f"   ├─ urn: {'✅' if has_urn else '❌'}")
        logger.info(f"   ├─ date: {post.published_at}")
        logger.info(f"   └─ date future: {'✅' if future_date else '❌'}")
        
        if has_urn:
            published_posts.append(post)
            logger.info(f"   → 📱 PUBLIÉ")
        elif is_scheduled and future_date:
            scheduled_posts.append(post)
            logger.info(f"   → ⏰ PROGRAMMÉ")
        else:
            draft_posts.append(post)
            logger.info(f"   → 📝 BROUILLON")
    
    logger.info(f"📈 RÉSULTAT: {len(draft_posts)} brouillons, {len(scheduled_posts)} programmés, {len(published_posts)} publiés")
    
    return render_template("historique.html", 
                         draft_posts=draft_posts, 
                         scheduled_posts=scheduled_posts, 
                         published_posts=published_posts)

@app.route("/debug_posts")
def debug_posts():
    """Route de diagnostic pour vérifier l'état des posts"""
    if 'profile' not in session:
        return "Non connecté"
    
    user = User.query.filter_by(sub=session['profile'].get("sub", "")).first()
    if not user:
        return "Utilisateur introuvable"
    
    posts = Post.query.filter_by(user_id=user.id).all()
    
    debug_html = f"""
    <h1>🔍 Debug Posts Utilisateur {user.id}</h1>
    <p>Total: {len(posts)} posts</p>
    <table border="1" style="border-collapse: collapse; width: 100%;">
    <tr>
        <th>ID</th>
        <th>Scheduled</th>
        <th>URN LinkedIn</th>
        <th>Date</th>
        <th>Contenu (50 chars)</th>
        <th>Classification</th>
    </tr>
    """
    
    now = datetime.utcnow()
    
    for post in posts:
        has_urn = bool(post.linkedin_post_urn)
        is_scheduled = bool(post.scheduled)
        future_date = post.published_at and post.published_at > now
        
        if has_urn:
            classification = "PUBLIÉ"
            color = "#4CAF50"
        elif is_scheduled and future_date:
            classification = "PROGRAMMÉ"
            color = "#2196F3"
        else:
            classification = "BROUILLON"
            color = "#FF9800"
        
        debug_html += f"""
        <tr style="background-color: {color}20;">
            <td>{post.id}</td>
            <td>{'✅' if is_scheduled else '❌'}</td>
            <td>{'✅' if has_urn else '❌'}</td>
            <td>{post.published_at}</td>
            <td>{(post.content or '')[:50]}...</td>
            <td style="font-weight: bold;">{classification}</td>
        </tr>
        """
    
    debug_html += """
    </table>
    <p><a href="/historique">← Retour historique</a></p>
    """
    
    return debug_html

@app.route("/parametres")
def parametres():
    if 'profile' not in session:
        return redirect(url_for("index"))
    return render_template("parametres.html", user=session['profile'])

@app.route("/calendar")
def calendar():
    if 'profile' not in session:
        return redirect(url_for("index"))

    user = User.query.filter_by(sub=session['profile']['sub']).first()
    if not user:
        return "Utilisateur introuvable"

    # CRITIQUE : Forcer une nouvelle requête sans cache
    db.session.expire_all()
    
    now = datetime.utcnow()
    # Posts programmés avec debug
    upcoming_posts = Post.query.filter_by(user_id=user.id, scheduled=True).filter(
        Post.linkedin_post_urn.is_(None),
        Post.published_at > now
    ).order_by(Post.published_at).all()
    
    logger.info(f"=== DEBUG CALENDAR pour utilisateur {user.id} ===")
    logger.info(f"Posts programmés trouvés: {len(upcoming_posts)}")
    for post in upcoming_posts:
        logger.info(f"Post {post.id}: date={post.published_at}, scheduled={post.scheduled}")

    return render_template("calendar.html", posts=upcoming_posts, now=now)

@app.route("/publish_scheduled")
def publish_scheduled():
    """Publication automatique des posts programmés - VERSION CORRIGÉE"""
    now = datetime.utcnow()
    
    # Récupérer TOUS les posts programmés dont l'heure est arrivée
    posts_to_publish = Post.query.filter(
        Post.scheduled == True, 
        Post.published_at <= now,
        Post.linkedin_post_urn.is_(None)  # Seulement ceux pas encore publiés
    ).all()

    count = 0
    errors = []
    
    logger.info(f"🔄 Vérification auto-publication: {len(posts_to_publish)} post(s) à traiter")
    
    for post in posts_to_publish:
        try:
            user = User.query.get(post.user_id)
            if not user:
                logger.warning(f"❌ Utilisateur introuvable pour le post {post.id}")
                continue

            # PROBLÈME PRINCIPAL : Il faut le token d'accès de chaque utilisateur
            # La publication automatique ne peut pas fonctionner sans les tokens individuels
            # Pour l'instant, on marque simplement le post comme "prêt à publier manuellement"
            
            logger.info(f"📅 Post {post.id} prêt pour publication manuelle")
            # On ne modifie rien - l'utilisateur devra publier manuellement
            
        except Exception as e:
            error_msg = f"Erreur post {post.id}: {str(e)}"
            logger.error(error_msg)
            errors.append(error_msg)

    if errors:
        logger.error(f"❌ Erreurs lors de la vérification: {'; '.join(errors)}")
    
    return f"✅ Vérification terminée. {len(posts_to_publish)} post(s) prêt(s) pour publication manuelle."



@app.errorhandler(500)
def handle_500(e):
    logger.error(f"Erreur 500: {str(e)}")
    
    # En mode développement, afficher des détails
    if app.debug:
        return f"""
        <h1>Erreur 500</h1>
        <p>Une erreur est survenue sur le serveur.</p>
        <h2>Détails</h2>
        <pre>{str(e)}</pre>
        <p><a href="/">Retour à l'accueil</a></p>
        """, 500
    
    # En production, message générique
    return """
    <h1>Erreur 500</h1>
    <p>Une erreur est survenue sur le serveur. L'équipe technique a été informée.</p>
    <p><a href="/">Retour à l'accueil</a></p>
    """, 500

# Ajout d'une route de test pour vérifier la connexion à la base de données
@app.route("/test-db")
def test_db():
    try:
        # Vérifier les tables existantes
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        
        # Compter les utilisateurs
        user_count = User.query.count()
        
        # Compter les posts
        post_count = Post.query.count()
        
        return f"""
        <h1>Test de la base de données</h1>
        <p>✅ Connexion à la base de données réussie</p>
        <h2>Tables existantes:</h2>
        <ul>{''.join([f'<li>{table}</li>' for table in tables])}</ul>
        <p>Nombre d'utilisateurs: {user_count}</p>
        <p>Nombre de posts: {post_count}</p>
        <p><a href="/">Retour à l'accueil</a></p>
        """
    except Exception as e:
        return f"""
        <h1>Erreur de test de la base de données</h1>
        <p>❌ La connexion à la base de données a échoué:</p>
        <pre>{str(e)}</pre>
        <p><a href="/">Retour à l'accueil</a></p>
        """, 500
        
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
