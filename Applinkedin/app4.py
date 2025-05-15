from flask import Flask, redirect, request, session, url_for
from urllib.parse import urlencode
import requests
import os
import google.generativeai as genai

app = Flask(__name__)
app.secret_key = os.urandom(24)

CLIENT_ID = "86occjps58doir"
CLIENT_SECRET = "WPL_AP1.C8C6uXjTbpJyQUx2.Y7COPg=="
REDIRECT_URI = "http://localhost:5000/callback"

LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
LINKEDIN_POSTS_URL = "https://api.linkedin.com/v2/ugcPosts?q=authors&sortBy=LAST_MODIFIED&count=5&authors=List(urn:li:person:{user_id})"

SCOPES = "openid email profile w_member_social"

genai.configure(api_key="AIzaSyCsfLrbLkNiJKSKdQsIps3KK47sxLNVCMQ")

def get_name_origin(name):
    try:
        model = genai.GenerativeModel('gemini-1.5-pro')
        prompt = f"Explique-moi en français l'origine et la signification du prénom {name} en 2 ou 3 phrases."
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"Erreur Gemini : {str(e)}"

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
    return f'''
    <h2 style="font-family:sans-serif;text-align:center;margin-top:100px">Connecte-toi avec LinkedIn</h2>
    <div style="text-align:center;margin-top:30px">
        <a href="{auth_url}"
           style="font-size:18px;padding:12px 24px;background:#0073b1;color:white;border-radius:5px;text-decoration:none;font-family:sans-serif">
            🔗 Se connecter avec LinkedIn
        </a>
    </div>
    '''

@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "Erreur : aucun code fourni par LinkedIn. Assure-toi que le redirect_uri est identique dans le code et dans ton application LinkedIn."

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    token_resp = requests.post(LINKEDIN_TOKEN_URL, data=data, headers=headers)

    if token_resp.status_code != 200:
        return f"Erreur d'obtention du token: {token_resp.text}"

    access_token = token_resp.json().get("access_token")
    session['access_token'] = access_token

    headers = {"Authorization": f"Bearer {access_token}"}
    userinfo_resp = requests.get(LINKEDIN_USERINFO_URL, headers=headers)

    if userinfo_resp.status_code != 200:
        return f"Erreur d'appel à /userinfo: {userinfo_resp.text}"

    userinfo = userinfo_resp.json()

    email = userinfo.get("email", "inconnu")
    name = userinfo.get("name", "")
    first_name = userinfo.get("given_name", "")
    last_name = userinfo.get("family_name", "")
    picture = userinfo.get("picture", "")
    language = userinfo.get("locale", {}).get("language", "")
    country = userinfo.get("locale", {}).get("country", "")
    email_verified = userinfo.get("email_verified", False)
    sub = userinfo.get("sub", "")

    try:
        name_origin = get_name_origin(first_name)
    except Exception as e:
        name_origin = "Désolé, impossible de récupérer l'origine du prénom."

    # Appel des posts si possible
    try:
        user_id = sub.split("_")[-1]  # urn:li:person:{id}
        posts_url = f"https://api.linkedin.com/v2/ugcPosts?q=authors&authors=List(urn:li:person:{user_id})&sortBy=LAST_MODIFIED&count=5"
        posts_resp = requests.get(posts_url, headers=headers)
        if posts_resp.status_code == 200:
            posts_data = posts_resp.json()
            posts_html = ""
            for post in posts_data.get("elements", []):
                content = post.get("specificContent", {}).get("com.linkedin.ugc.ShareContent", {}).get("shareCommentary", {}).get("text", "")
                posts_html += f"<li style='margin-bottom:10px;'>{content}</li>"
            if not posts_html:
                posts_html = "<li>Aucun post récent trouvé.</li>"
            posts_html = f"<ul style='text-align:left;width:60%;margin:0 auto'>{posts_html}</ul>"
        else:
            posts_html = "<p style='color:gray'>Impossible de charger les posts.</p>"
    except Exception as e:
        posts_html = f"<p style='color:red'>Erreur lors de la récupération des posts : {str(e)}</p>"

    return f'''
    <html>
    <head><title>Profil LinkedIn</title></head>
    <body style="font-family:sans-serif;text-align:center;margin-top:50px">
        <h1>Bienvenue, {first_name} {last_name} 👋</h1>
        <img src="{picture}" alt="Photo de profil" width="200" style="border-radius:50%;margin-top:20px" />
        <p style="font-size:18px;margin-top:20px"><strong>Nom complet :</strong> {name}</p>
        <p style="font-size:18px"><strong>Email :</strong> {email} {'✅ vérifié' if email_verified else '❌ non vérifié'}</p>
        <p style="font-size:18px"><strong>Pays :</strong> {country.upper()} - <strong>Langue :</strong> {language}</p>
        <p style="font-size:18px"><strong>Identifiant LinkedIn (sub) :</strong> {sub}</p>
        <div style="margin-top:30px;padding:20px;background-color:#f9f9f9;border-radius:10px;width:60%;margin-left:auto;margin-right:auto">
            <h3>✨ Origine de ton prénom :</h3>
            <p style="font-size:16px;">{name_origin}</p>
        </div>
        <div style="margin-top:50px;padding:20px;background-color:#eef;border-radius:10px;width:60%;margin-left:auto;margin-right:auto">
            <h3>📰 Derniers posts LinkedIn :</h3>
            {posts_html}
        </div>
        <p style="margin-top:30px;font-size:14px;color:#999">Connexion réussie via LinkedIn OAuth2</p>
        <p style="margin-top:30px">
            <a href="/logout" style="font-size:16px;color:red;text-decoration:none">🔒 Se déconnecter</a>
        </p>
    </body>
    </html>
    '''

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True, port=5000)
