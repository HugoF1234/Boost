from flask import Flask, redirect, request, session, url_for, render_template_string
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
LINKEDIN_POSTS_URL = "https://api.linkedin.com/v2/ugcPosts"

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
    email = userinfo.get("email", "inconnu")
    name = userinfo.get("name", "")
    first_name = userinfo.get("given_name", "")
    last_name = userinfo.get("family_name", "")
    picture = userinfo.get("picture", "")
    language = userinfo.get("locale", {}).get("language", "")
    country = userinfo.get("locale", {}).get("country", "")
    email_verified = userinfo.get("email_verified", False)

    try:
        name_origin = get_name_origin(first_name)
    except:
        name_origin = "Origine du prénom indisponible."

    return render_template_string('''
    <html><head><title>BOOSTING</title></head>
    <body style="font-family:sans-serif;text-align:center;margin-top:50px">
        <h1>Bienvenue, {{ first_name }} {{ last_name }} 👋</h1>
        <img src="{{ picture }}" width="200" style="border-radius:50%;margin-top:20px" />
        <p><strong>Email :</strong> {{ email }} {% if email_verified %}✅{% else %}❌{% endif %}</p>
        <p><strong>Langue :</strong> {{ language }} — <strong>Pays :</strong> {{ country }}</p>

        <div style="margin-top:30px;background:#f9f9f9;padding:20px;border-radius:10px;width:60%;margin:auto">
            <h3>✨ Origine du prénom</h3><p>{{ name_origin }}</p>
        </div>

        <div style="margin-top:40px;background:#eef;padding:20px;border-radius:10px;width:60%;margin:auto">
            <h3>💬 Générer un post avec Gemini</h3>
            <form action="/generate" method="post">
                <input type="text" name="prompt" placeholder="Ex: écris un post sur le vélo" style="width:70%;padding:10px;font-size:16px" required>
                <button type="submit" style="padding:10px 20px;font-size:16px;margin-left:10px">✨ Générer</button>
            </form>
        </div>

        <div style="margin-top:40px;background:#d0f0d0;padding:20px;border-radius:10px;width:60%;margin:auto">
            <h3>📝 Prévisualisation du post LinkedIn</h3>
            <form action="/publish" method="post">
                <textarea name="post_content" rows="10" cols="80" placeholder="Ton post généré apparaîtra ici..." required>{{ session.get('draft', '') }}</textarea><br><br>
                <button type="submit" style="padding:10px 20px;font-size:16px;background:#0073b1;color:white;border:none;border-radius:5px">📤 Publier sur LinkedIn</button>
            </form>
        </div>
        <p style="margin-top:30px"><a href="/logout" style="color:red">🔒 Se déconnecter</a></p>
    </body></html>
    ''', first_name=first_name, last_name=last_name, picture=picture, email=email,
         email_verified=email_verified, language=language, country=country, name_origin=name_origin)

@app.route("/generate", methods=["POST"])
def generate():
    prompt = request.form.get("prompt")
    try:
        model = genai.GenerativeModel("gemini-1.5-pro")
        response = model.generate_content(prompt)
        session['draft'] = response.text.strip()
    except Exception as e:
        session['draft'] = f"Erreur Gemini : {str(e)}"
    return redirect("/callback")

@app.route("/publish", methods=["POST"])
def publish():
    access_token = session.get("access_token")
    if not access_token:
        return redirect(url_for("index"))

    content = request.form.get("post_content")
    if not content:
        return "Aucun contenu reçu."

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0"
    }

    me_resp = requests.get("https://api.linkedin.com/v2/me", headers=headers)
    if me_resp.status_code != 200:
        return f"Erreur lors de la récupération de l'utilisateur : {me_resp.text}"
    user_id = me_resp.json().get("id")
    urn = f"urn:li:person:{user_id}"

    post_data = {
        "author": urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": content},
                "shareMediaCategory": "NONE"
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
    }
    post_resp = requests.post("https://api.linkedin.com/v2/ugcPosts", headers=headers, json=post_data)

    if post_resp.status_code == 201:
        session['draft'] = ""
        return "<h2 style='text-align:center;margin-top:50px'>✅ Ton post a bien été publié sur LinkedIn !</h2><p style='text-align:center'><a href='/callback'>Retour</a></p>"
    else:
        return f"<h2>❌ Erreur lors de la publication :</h2><pre>{post_resp.text}</pre><p><a href='/callback'>Retour</a></p>"

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True, port=5000)
