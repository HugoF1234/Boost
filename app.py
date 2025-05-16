from flask import Flask, redirect, request, session, url_for, render_template, make_response
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
app = Flask(__name__)
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
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyB434P__wR_o_rr5Q3PjOULqyKhMANRtgk")
genai.configure(api_key=GEMINI_API_KEY)

# -----------------------
# ROUTES FLASK
# -----------------------

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
    
@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if 'profile' not in session:
        return redirect(url_for("index"))

    draft = ""
    # Récupérer l'utilisateur
    user = User.query.filter_by(sub=session['profile'].get("sub", "")).first()
    
    # Statistiques pour le tableau de bord
    scheduled_posts = 0
    if user:
        # Nombre de posts programmés
        from datetime import datetime
        now = datetime.utcnow()
        scheduled_posts = Post.query.filter_by(user_id=user.id, scheduled=True).filter(Post.published_at > now).count()
    
    if request.method == "POST":
        prompt = request.form.get("prompt")
        tone = request.form.get("tone", "professionnel")
        try:
            model = genai.GenerativeModel("gemini-1.5-pro")
            extended_prompt = f"Écris un post LinkedIn sur : {prompt}. Le ton doit être {tone}. Tu redigeras le post de la maniere la plus humaine possible"
            response = model.generate_content(extended_prompt)
            draft = response.text.strip()
        except Exception as e:
            draft = f"Erreur Gemini : {str(e)}"

    session['draft'] = draft
    # Passer les variables supplémentaires au template
    return render_template(
        "dashboard.html", 
        **session['profile'], 
        draft=draft,
        scheduled_posts=scheduled_posts,
        posts=user.posts if user else []
    )

    
from datetime import datetime


@app.route("/publish", methods=["POST"])
def publish():
    access_token = session.get("access_token")
    if not access_token:
        return redirect(url_for("index"))

    content = request.form.get("post_content")
    date_str = request.form.get("publish_time")
    publish_now = request.form.get("publish_now")  # <- case à cocher

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

    media_assets = []
    uploaded_files = request.files.getlist("images[]")

    for file in uploaded_files:
        if file.filename:
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
                print(f"Erreur registre upload: {reg_resp.text}")
                continue

            upload_info = reg_resp.json().get("value", {})
            upload_url = upload_info.get("uploadMechanism", {}).get("com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest", {}).get("uploadUrl")
            asset = upload_info.get("asset")

            if not upload_url or not asset:
                continue

            upload_headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": file.content_type or "image/png"
            }

            file_bytes = file.read()
            put_resp = requests.put(upload_url, data=file_bytes, headers=upload_headers)

            if put_resp.status_code not in [200, 201]:
                print(f"Erreur upload image: {put_resp.text}")
                continue

            media_assets.append({
                "status": "READY",
                "media": asset
            })

    share_media_category = "IMAGE" if media_assets else "NONE"

    post_data = {
        "author": urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": content},
                "shareMediaCategory": share_media_category,
                "media": media_assets
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        }
    }

    post_resp = requests.post(LINKEDIN_POSTS_URL, headers=headers, json=post_data)

    if post_resp.status_code == 201:
        if user:
            published_post = Post(content=content, published_at=now, user_id=user.id, scheduled=False)
            db.session.add(published_post)
            db.session.commit()

        session['draft'] = ""
        return redirect(url_for("dashboard"))
    else:
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
