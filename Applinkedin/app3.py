from flask import Flask, redirect, request, session, url_for
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

SCOPES = "openid profile email"


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
    return f'''
    <h2 style="font-family:sans-serif;text-align:center;margin-top:100px">Connecte-toi avec LinkedIn</h2>
    <div style="text-align:center;margin-top:30px">
        <a href="{LINKEDIN_AUTH_URL}?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&scope={SCOPES}&state=random123&prompt=login"
           style="font-size:18px;padding:12px 24px;background:#0073b1;color:white;border-radius:5px;text-decoration:none;font-family:sans-serif">
            🔗 Se connecter avec LinkedIn
        </a>
    </div>
    '''

@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "Erreur : aucun code fourni par LinkedIn"

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
        return f"Erreur userinfo: {userinfo_resp.text}"

    userinfo = userinfo_resp.json()

    name = userinfo.get("name", "Utilisateur")
    email = userinfo.get("email", "email inconnu")
    picture = userinfo.get("picture", "")
    country = userinfo.get("locale", {}).get("country", "")
    language = userinfo.get("locale", {}).get("language", "")


    try:
        name_origin = get_name_origin(name.split(' ')[0])
    except Exception as e:
        name_origin = "Désolé, impossible de récupérer l'origine du prénom."

    return f'''
    <html>
    <head><title>Profil LinkedIn</title></head>
    <body style="font-family:sans-serif;text-align:center;margin-top:50px">
        <h1>Bienvenue, {name} 👋</h1>
        <img src="{picture}" alt="Photo de profil" width="200" style="border-radius:50%;margin-top:20px" />
        <p style="font-size:18px;margin-top:20px"><strong>Email :</strong> {email}</p>
        <p style="font-size:18px"><strong>Pays :</strong> {country.upper()} - <strong>Langue :</strong> {language}</p>
        <div style="margin-top:30px;padding:20px;background-color:#f9f9f9;border-radius:10px;width:60%;margin-left:auto;margin-right:auto">
            <h3>✨ Origine de ton prénom :</h3>
            <p style="font-size:16px;">{name_origin}</p>
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
