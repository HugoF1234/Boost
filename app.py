from flask import Flask, redirect, request, session, url_for, render_template, make_response, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from sqlalchemy import inspect
from urllib.parse import urlencode
from datetime import datetime
import requests
import os
import google.generativeai as genai
import logging
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

# Fonction d'initialisation de la base de données
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
            
            # Vérifier les tables après création
            existing_tables = inspector.get_table_names()
            logger.info(f"Tables existantes après création: {existing_tables}")
            
            # Vérifier spécifiquement les tables users et posts
            if 'users' in existing_tables:
                logger.info("Table 'users' existe")
            else:
                logger.warning("Table 'users' n'existe pas malgré la tentative de création")
                
            if 'posts' in existing_tables:
                logger.info("Table 'posts' existe")
            else:
                logger.warning("Table 'posts' n'existe pas malgré la tentative de création")
        
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
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyD76qCZzbr9P74etHmr8qWb1qoe7eapDbc")
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
import re
import html


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

def get_news_by_keyword(keyword, days=30, language="fr"):
    """
    Récupère les actualités en fonction d'un mot-clé, sans filtrage par secteur
    
    Args:
        keyword (str): Mot-clé de recherche
        days (int, optional): Nombre de jours pour les actualités récentes
        language (str, optional): Langue des articles (fr, en)
        
    Returns:
        list: Liste d'articles d'actualité
    """
    # Vérifier si nous avons un cache pour cette requête
    cache_key = f"{keyword}_{language}_{days}.json"
    cache_path = os.path.join(cache_dir, cache_key)
    
    # Vérifier si un cache valide existe (moins de 3 heures)
    if os.path.exists(cache_path):
        file_modified_time = os.path.getmtime(cache_path)
        now = datetime.now().timestamp()
        
        # Si le cache a moins de 3 heures
        if now - file_modified_time < 10800:  # 3 heures en secondes
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cached_data = json.load(f)
                    logger.info(f"Utilisation du cache pour: {keyword}")
                    return cached_data
            except Exception as e:
                logger.error(f"Erreur de lecture du cache: {str(e)}")
    
    # Si pas de cache valide, construire une requête directe à NewsAPI
    date_from = (datetime.utcnow() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    # Optimiser la requête avec des opérateurs de recherche
    formatted_keyword = keyword
    if ' ' in keyword and not (keyword.startswith('"') and keyword.endswith('"')):
        # Ajouter des guillemets pour une recherche exacte de phrases
        formatted_keyword = f'"{keyword}"'
    
    # Préparer les paramètres de la requête
    params = {
        'q': formatted_keyword,
        'from': date_from,
        'sortBy': 'relevancy',
        'language': language,
        'apiKey': NEWS_API_KEY,
        'pageSize': 100
    }
    
    logger.info(f"Requête NewsAPI par mot-clé: {NEWS_API_URL}")
    logger.info(f"Paramètres: q={formatted_keyword}, lang={language}, from={date_from}")
    
    try:
        # Appel à l'API
        response = requests.get(NEWS_API_URL, params=params, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            articles = data.get('articles', [])
            
            # Filtrer les articles sans contenu
            valid_articles = []
            for article in articles:
                if article.get('title') and article.get('description'):
                    try:
                        # Formater la date
                        date_str = article.get('publishedAt', '')
                        date_obj = datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%SZ')
                        article['formatted_date'] = date_obj.strftime('%d/%m/%Y')
                    except:
                        article['formatted_date'] = 'Date inconnue'
                    
                    valid_articles.append(article)
            
            # Sauvegarder les résultats dans le cache
            try:
                with open(cache_path, 'w', encoding='utf-8') as f:
                    json.dump(valid_articles, f, ensure_ascii=False)
                    logger.info(f"Cache créé pour: {keyword}")
            except Exception as e:
                logger.error(f"Erreur d'écriture du cache: {str(e)}")
            
            return valid_articles
            
        else:
            error_text = response.text
            logger.error(f"Erreur API {response.status_code}: {error_text}")
            raise Exception(f"Erreur de l'API NewsAPI ({response.status_code})")
            
    except Exception as e:
        logger.error(f"Exception lors de la recherche par mot-clé: {str(e)}")
        raise

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

def get_news_by_sector(sector, keywords=None, days=3, language="fr"):
    """
    Version avec cache de la fonction de récupération d'actualités
    
    Args:
        sector (str): Le secteur d'activité (tech, finance, etc.)
        keywords (str, optional): Mots-clés supplémentaires
        days (int, optional): Nombre de jours pour les actualités récentes
        language (str, optional): Langue des articles (fr, en)
        
    Returns:
        list: Liste d'articles d'actualité
    """
    # Mapping des secteurs vers des termes de recherche pertinents
    sector_keywords = {
        'tech': 'technologie informatique développement logiciel innovation internet',
        'marketing': 'marketing numérique publicité stratégie marque réseaux sociaux',
        'finance': 'finance banque investissement économie bourse',
        'sante': 'santé médecine bien-être médical pharmacie',
        'education': 'éducation enseignement formation apprentissage école',
        'rh': 'ressources humaines recrutement emploi talent management',
        'consulting': 'conseil consulting stratégie entreprise management',
        'retail': 'commerce distribution retail vente consommation',
        # Définir d'autres secteurs selon vos besoins
    }
    
    # Construire la requête de recherche
    search_query = sector_keywords.get(sector, sector)
    if keywords:
        search_query += f" {keywords}"
    
    # Utiliser la fonction de cache
    return get_cached_news(search_query, language, days)

def get_news_by_sector_actual(sector, keywords=None, days=7, language="fr"):
    """
    VERSION CORRIGÉE - Récupère les actualités avec meilleur debugging
    """
    # Mapping des secteurs avec termes plus simples
    sector_keywords = {
        'tech': 'technologie',
        'marketing': 'marketing',
        'finance': 'finance',
        'sante': 'santé',
        'education': 'éducation',
        'rh': 'emploi',
        'consulting': 'conseil',
        'retail': 'commerce',
    }
    
    # Construire une requête plus simple
    search_query = sector_keywords.get(sector, sector)
    if keywords:
        search_query = f"{keywords}"  # Utiliser directement les mots-clés
    
    # Réduire la période pour éviter les limites
    date_from = (datetime.utcnow() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    # Paramètres de requête simplifiés
    params = {
        'q': search_query,
        'from': date_from,
        'sortBy': 'publishedAt',  # Trier par date
        'language': language,
        'apiKey': NEWS_API_KEY,
        'pageSize': 50  # Réduire pour éviter les limites
    }
    
    # Log détaillé pour le débogage
    logger.info(f"🔍 REQUÊTE NewsAPI:")
    logger.info(f"   URL: {NEWS_API_URL}")
    logger.info(f"   Query: {search_query}")
    logger.info(f"   From: {date_from}")
    logger.info(f"   Language: {language}")
    logger.info(f"   PageSize: {params['pageSize']}")
    
    try:
        # Appel à l'API avec timeout
        response = requests.get(NEWS_API_URL, params=params, timeout=10)
        
        # Log de la réponse complète
        logger.info(f"📡 RÉPONSE NewsAPI:")
        logger.info(f"   Status Code: {response.status_code}")
        logger.info(f"   Headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            data = response.json()
            total_results = data.get('totalResults', 0)
            articles = data.get('articles', [])
            
            logger.info(f"✅ SUCCÈS:")
            logger.info(f"   Total Results: {total_results}")
            logger.info(f"   Articles retournés: {len(articles)}")
            
            # Debug des premiers articles
            for i, article in enumerate(articles[:3]):
                logger.info(f"   Article {i+1}: {article.get('title', 'No title')[:50]}...")
            
            # Filtrer et formater les articles
            valid_articles = []
            for article in articles:
                if article.get('title') and article.get('description'):
                    try:
                        date_str = article.get('publishedAt', '')
                        if date_str:
                            date_obj = datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%SZ')
                            article['formatted_date'] = date_obj.strftime('%d/%m/%Y')
                        else:
                            article['formatted_date'] = 'Date inconnue'
                    except:
                        article['formatted_date'] = 'Date inconnue'
                    
                    valid_articles.append(article)
            
            logger.info(f"   Articles valides: {len(valid_articles)}")
            return valid_articles
            
        elif response.status_code == 429:
            logger.error("🚫 ERREUR 429: Limite de requêtes dépassée")
            logger.error("   Attendez quelques minutes avant de réessayer")
            raise Exception("Limite d'API atteinte. Réessayez dans quelques minutes.")
            
        elif response.status_code == 401:
            logger.error("🚫 ERREUR 401: Clé API invalide")
            logger.error(f"   Clé utilisée: {NEWS_API_KEY[:10]}...")
            raise Exception("Clé API NewsAPI invalide")
            
        else:
            error_text = response.text
            logger.error(f"🚫 ERREUR API {response.status_code}: {error_text}")
            raise Exception(f"Erreur de l'API NewsAPI ({response.status_code})")
            
    except requests.exceptions.Timeout:
        logger.error("⏱️ TIMEOUT: L'API ne répond pas")
        raise Exception("L'API ne répond pas - délai d'attente dépassé")
    except requests.exceptions.ConnectionError:
        logger.error("🌐 ERREUR CONNEXION: Impossible de joindre l'API")
        raise Exception("Impossible de se connecter à l'API")
    except Exception as e:
        logger.error(f"❌ EXCEPTION: {str(e)}")
        raise

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
                
                # CORRECTION: Récupérer les données directement depuis le formulaire
                article_data = {
                    'title': request.form.get('article_title', ''),
                    'description': request.form.get('article_description', ''),
                    'source': {'name': request.form.get('article_source', '')},
                    'url': request.form.get('article_url', ''),
                    'formatted_date': request.form.get('article_date', ''),
                    'urlToImage': request.form.get('article_image', '')
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
                    
                    # CORRECTION: Rediriger vers le dashboard avec un paramètre de succès
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
            # Si l'utilisateur a entré un mot-clé, effectuer une recherche générale
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
    session.clear()
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
    """Route dédiée à la sélection d'articles"""
    if 'profile' not in session:
        return jsonify({'error': 'Non authentifié'}), 401
    
    try:
        # Récupérer les données JSON de l'article
        article_data = request.get_json()
        
        if not article_data:
            # Fallback : essayer de récupérer depuis le formulaire
            article_data = {
                'title': request.form.get('title', ''),
                'description': request.form.get('description', ''),
                'source': {'name': request.form.get('source', '')},
                'url': request.form.get('url', ''),
                'formatted_date': request.form.get('date', ''),
                'urlToImage': request.form.get('image', '')
            }
        
        logger.info(f"Article sélectionné: {article_data.get('title', 'Sans titre')}")
        
        # Valider les données minimales
        if not article_data.get('title') or not article_data.get('description'):
            return jsonify({'error': 'Données d\'article incomplètes'}), 400
        
        # Stocker dans la session
        session['selected_article'] = article_data
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
    
    # CORRECTION: Récupérer le message de succès de l'article
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
        
        # CORRECTION: Vérifier si l'utilisateur veut générer un post basé sur un article sélectionné
        if 'generate_from_article' in request.form and selected_article:
            try:
                logger.info("Génération de post à partir de l'article sélectionné")
                perspective = request.form.get("perspective", "neutre")
                format_type = request.form.get("format", "standard")
                
                # Récupérer les instructions personnalisées
                custom_instructions = request.form.get("custom_instructions", "").strip()
                
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
                
                # Construire le prompt avec les instructions personnalisées si présentes
                article_prompt = f"""
                Rédige un post LinkedIn sur l'actualité suivante:
                
                Titre: {selected_article.get('title')}
                Description: {selected_article.get('description')}
                Source: {selected_article.get('source', {}).get('name')}
                
                Instructions:
                - Ton: {tone}
                - Perspective: {perspective}
                - Format: {format_text}
                - Secteur d'expertise: {user.secteur if user and user.secteur else "general"}
                - Inclus 2-3 hashtags pertinents
                - Le post doit être personnel, comme si la personne donnait son avis sur cette actualité
                - Maximum 800 caractères
                - Format adapté à LinkedIn
                """
                
                # Ajouter les instructions personnalisées si elles existent
                if custom_instructions:
                    article_prompt += f"\nInstructions supplémentaires: {custom_instructions}"
                
                response = model.generate_content(article_prompt)
                draft = response.text.strip()
                
                # CORRECTION: Ne pas effacer l'article immédiatement, le garder pour l'affichage
                logger.info("Post généré avec succès à partir de l'article")
                
            except Exception as e:
                draft = f"Erreur Gemini : {str(e)}"
                logger.error(f"Erreur lors de la génération du post: {str(e)}")
        else:
            # Génération standard basée sur un prompt optimisé LinkedIn
            try:
                model = genai.GenerativeModel("gemini-2.0-flash")
                
                # Récupérer les intérêts et secteur de l'utilisateur (uniquement pour ton personnel)
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

# Ajout à app.py pour gérer les images multiples

@app.route("/publish", methods=["POST"])
def publish():
    access_token = session.get("access_token")
    if not access_token:
        return redirect(url_for("index"))

    content = request.form.get("post_content")
    date_str = request.form.get("publish_time")
    publish_now = request.form.get("publish_now")

    if not content:
        return "Aucun contenu reçu."

    try:
        publish_time = datetime.strptime(date_str, "%Y-%m-%dT%H:%M")
    except (ValueError, TypeError):
        publish_time = datetime.utcnow()

    now = datetime.utcnow()

    profile = session.get('profile')
    sub = profile.get("sub", "")
    user_id = sub.split("_")[-1]
    urn = f"urn:li:person:{user_id}"
    user = User.query.filter_by(sub=sub).first()

    # ✅ Cas planification (date future + pas de case cochée)
    if publish_time > now and not publish_now:
        if user:
            planned_post = Post(content=content, published_at=publish_time, user_id=user.id, scheduled=True)
            db.session.add(planned_post)
            db.session.commit()
        return redirect(url_for("calendar"))

    # ✅ Sinon → publication immédiate
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0"
    }

    # Traiter les mentions pour LinkedIn
    processed_content, mention_entities = process_mentions_for_linkedin(content)

    # ✅ NOUVELLE GESTION D'IMAGES MULTIPLES
    media_assets = []
    uploaded_files = request.files.getlist("images[]")  # getlist pour multiple files
    
    # Limiter à 9 images maximum (limite LinkedIn)
    max_images = min(len(uploaded_files), 9)
    
    for i in range(max_images):
        file = uploaded_files[i]
        if file and file.filename:
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
                    logger.error(f"Erreur registre upload image {i+1}: {reg_resp.text}")
                    continue

                upload_info = reg_resp.json().get("value", {})
                upload_url = upload_info.get("uploadMechanism", {}).get("com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest", {}).get("uploadUrl")
                asset = upload_info.get("asset")

                if not upload_url or not asset:
                    logger.error(f"Upload URL ou asset manquant pour image {i+1}")
                    continue

                # 2. Uploader l'image
                upload_headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": file.content_type or "image/png"
                }

                file_bytes = file.read()
                put_resp = requests.put(upload_url, data=file_bytes, headers=upload_headers)

                if put_resp.status_code not in [200, 201]:
                    logger.error(f"Erreur upload image {i+1}: {put_resp.text}")
                    continue

                # 3. Ajouter à la liste des médias
                media_assets.append({
                    "status": "READY",
                    "media": asset,
                    "description": {
                        "text": f"Image {i+1}"
                    }
                })
                
                logger.info(f"Image {i+1} uploadée avec succès: {asset}")
                
            except Exception as e:
                logger.error(f"Exception lors de l'upload de l'image {i+1}: {str(e)}")
                continue

    # Déterminer le type de média
    if len(media_assets) == 0:
        share_media_category = "NONE"
        media_content = []
    elif len(media_assets) == 1:
        share_media_category = "IMAGE"
        media_content = media_assets
    else:
        share_media_category = "IMAGE"  # LinkedIn supporte les images multiples
        media_content = media_assets

    # Construire le payload de post avec les mentions si présentes
    post_data = {
        "author": urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": processed_content},
                "shareMediaCategory": share_media_category,
                "media": media_content
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        }
    }
    
    # Ajouter les entités de mention si présentes
    if mention_entities:
        post_data["specificContent"]["com.linkedin.ugc.ShareContent"]["mentions"] = mention_entities

    # Publier le post
    post_resp = requests.post(LINKEDIN_POSTS_URL, headers=headers, json=post_data)

    if post_resp.status_code == 201:
        if user:
            published_post = Post(content=content, published_at=now, user_id=user.id, scheduled=False)
            db.session.add(published_post)
            db.session.commit()

        session['draft'] = ""
        return redirect(url_for("dashboard"))
    else:
        logger.error(f"Erreur publication: {post_resp.text}")
        return f"<h2>❌ Erreur lors de la publication :</h2><pre>{post_resp.text}</pre><p><a href='/dashboard'>Retour</a></p>"

@app.route("/edit_post/<int:post_id>", methods=["GET", "POST"])
def edit_post(post_id):
    if 'profile' not in session:
        return redirect(url_for("index"))
    
    # Récupérer l'utilisateur et vérifier qu'il existe
    user = User.query.filter_by(sub=session['profile'].get("sub", "")).first()
    if not user:
        return "Utilisateur introuvable"
    
    # Récupérer le post et vérifier qu'il appartient à l'utilisateur
    post = Post.query.filter_by(id=post_id, user_id=user.id).first()
    if not post:
        return "Post introuvable ou vous n'avez pas les droits pour le modifier"
    
    # Si le post n'est pas programmé, rediriger vers l'historique
    if not post.scheduled:
        return redirect(url_for("historique"))
    
    if request.method == "POST":
        # Mettre à jour le contenu du post
        post.content = request.form.get("post_content", "")
        
        # Mettre à jour la date de publication si fournie
        publish_time = request.form.get("publish_time")
        if publish_time:
            try:
                post.published_at = datetime.strptime(publish_time, "%Y-%m-%dT%H:%M")
            except (ValueError, TypeError):
                pass  # Conserver la date actuelle en cas d'erreur
        
        # Publier maintenant si demandé
        if request.form.get("publish_now"):
            # Logique pour publier immédiatement sur LinkedIn
            try:
                # Récupérer le token d'accès
                access_token = session.get("access_token")
                if not access_token:
                    return "Token d'accès LinkedIn non disponible, veuillez vous reconnecter"
                
                # Préparer les données pour l'API LinkedIn
                sub = user.sub
                user_id = sub.split("_")[-1]
                urn = f"urn:li:person:{user_id}"
                
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                    "X-Restli-Protocol-Version": "2.0.0"
                }
                
                post_data = {
                    "author": urn,
                    "lifecycleState": "PUBLISHED",
                    "specificContent": {
                        "com.linkedin.ugc.ShareContent": {
                            "shareCommentary": {"text": post.content},
                            "shareMediaCategory": "NONE",
                            "media": []
                        }
                    },
                    "visibility": {
                        "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
                    }
                }
                
                post_resp = requests.post(LINKEDIN_POSTS_URL, headers=headers, json=post_data)
                
                if post_resp.status_code == 201:
                    # Marquer comme publié et non programmé
                    post.scheduled = False
                    post.published_at = datetime.utcnow()
                    db.session.commit()
                    
                    return redirect(url_for("historique"))
                else:
                    return f"<h2>❌ Erreur lors de la publication :</h2><pre>{post_resp.text}</pre><p><a href='/calendar'>Retour</a></p>"
                
            except Exception as e:
                return f"<h2>❌ Erreur lors de la publication :</h2><pre>{str(e)}</pre><p><a href='/calendar'>Retour</a></p>"
        
        # Sauvegarder les modifications
        db.session.commit()
        
        return redirect(url_for("calendar"))
    
    # Formater la date pour l'input datetime-local
    formatted_date = post.published_at.strftime("%Y-%m-%dT%H:%M") if post.published_at else ""
    
    return render_template("edit_post.html", post=post, formatted_date=formatted_date)

@app.route("/delete_post/<int:post_id>", methods=["GET", "POST"])
def delete_post(post_id):
    if 'profile' not in session:
        return redirect(url_for("index"))
    
    # Récupérer l'utilisateur et vérifier qu'il existe
    user = User.query.filter_by(sub=session['profile'].get("sub", "")).first()
    if not user:
        return "Utilisateur introuvable"
    
    # Récupérer le post et vérifier qu'il appartient à l'utilisateur
    post = Post.query.filter_by(id=post_id, user_id=user.id).first()
    if not post:
        return "Post introuvable ou vous n'avez pas les droits pour le supprimer"
    
    if request.method == "POST":
        # Confirmer la suppression
        db.session.delete(post)
        db.session.commit()
        
        # Rediriger vers le calendrier ou l'historique selon le type de post
        if post.scheduled:
            return redirect(url_for("calendar"))
        else:
            return redirect(url_for("historique"))
    
    # Afficher la page de confirmation
    return render_template("delete_post.html", post=post)


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

    return render_template("profil.html", **session['profile'])

@app.route("/historique")
def historique():
    if 'profile' not in session:
        return redirect(url_for("index"))

    sub = session["profile"].get("sub", "")
    user = User.query.filter_by(sub=sub).first()

    if not user:
        return "<p>Utilisateur introuvable en base.</p>"

    # Récupérer les objets Post complets au lieu de juste le contenu
    posts = Post.query.filter_by(user_id=user.id).order_by(Post.published_at.desc()).all()
    return render_template("historique.html", posts=posts)

@app.route("/parametres")
def parametres():
    if 'profile' not in session:
        return redirect(url_for("index"))
    return render_template("parametres.html")

@app.route("/calendar")
def calendar():
    if 'profile' not in session:
        return redirect(url_for("index"))

    user = User.query.filter_by(sub=session['profile']['sub']).first()
    if not user:
        return "Utilisateur introuvable"

    # Ajout de la date actuelle pour le calcul de la différence de temps
    from datetime import datetime
    now = datetime.utcnow()
    upcoming_posts = Post.query.filter_by(user_id=user.id, scheduled=True).filter(Post.published_at > now).order_by(Post.published_at).all()

    return render_template("calendar.html", posts=upcoming_posts, now=now)
#http://localhost:5000/publish_scheduled

@app.route("/publish_scheduled")
def publish_scheduled():
    now = datetime.utcnow()
    posts_to_publish = Post.query.filter(Post.scheduled == True, Post.published_at <= now).all()

    count = 0
    for post in posts_to_publish:
        user = User.query.get(post.user_id)
        if not user:
            continue

        access_token = session.get("access_token")
        if not access_token:
            continue

        sub = user.sub
        user_id = sub.split("_")[-1]
        urn = f"urn:li:person:{user_id}"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0"
        }

        post_data = {
            "author": urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": post.content},
                    "shareMediaCategory": "NONE",
                    "media": []
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            }
        }

        post_resp = requests.post(LINKEDIN_POSTS_URL, headers=headers, json=post_data)
        if post_resp.status_code == 201:
            post.scheduled = False
            db.session.commit()
            count += 1
        else:
            print("Erreur LinkedIn:", post_resp.text)

    return f"✅ {count} post(s) planifié(s) publiés automatiquement."


@app.route("/logout")
def logout():
    session.clear()
    resp = make_response(redirect("/"))
    resp.set_cookie('linkedin_session', '', expires=0)
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp
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
