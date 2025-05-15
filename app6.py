from flask import Flask, redirect, request, session, url_for, render_template, make_response
from urllib.parse import urlencode
import requests
import os
import google.generativeai as genai

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['SESSION_COOKIE_NAME'] = 'linkedin_session'

CLIENT_ID = "86occjps58doir"
CLIENT_SECRET = "WPL_AP1.C8C6uXjTbpJyQUx2.Y7COPg=="
REDIRECT_URI = "http://localhost:5000/callback"

LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
LINKEDIN_ASSET_REGISTRATION_URL = "https://api.linkedin.com/v2/assets?action=registerUpload"
LINKEDIN_POSTS_URL = "https://api.linkedin.com/v2/ugcPosts"

SCOPES = "openid email profile w_member_social"

genai.configure(api_key="AIzaSyB434P__wR_o_rr5Q3PjOULqyKhMANRtgk")

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

    return redirect(url_for("dashboard"))

@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if 'profile' not in session:
        return redirect(url_for("index"))

    draft = ""
    if request.method == "POST":
        prompt = request.form.get("prompt")
        tone = request.form.get("tone", "professionnel")
        try:
            model = genai.GenerativeModel("gemini-1.5-pro")
            extended_prompt = f"Écris un post LinkedIn sur : {prompt}. Le ton doit être {tone}."
            response = model.generate_content(extended_prompt)
            draft = response.text.strip()
        except Exception as e:
            draft = f"Erreur Gemini : {str(e)}"

    session['draft'] = draft
    return render_template("dashboard.html", **session['profile'], draft=draft)

@app.route("/publish", methods=["POST"])
def publish():
    access_token = session.get("access_token")
    if not access_token:
        return redirect(url_for("index"))

    content = request.form.get("post_content")
    if not content:
        return "Aucun contenu reçu."

    profile = session.get('profile')
    sub = profile.get("sub", "")
    user_id = sub.split("_")[-1]
    urn = f"urn:li:person:{user_id}"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0"
    }

    media_assets = []
    uploaded_files = request.files.getlist("images[]")  # ← assure-toi que le champ HTML a name="images[]"

    for file in uploaded_files:
        if file.filename:
            # Étape 1 : Demande de registre
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
                print("Données d'upload incomplètes")
                continue

            # Étape 2 : Upload effectif du fichier
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
        session['draft'] = ""
        return redirect(url_for("dashboard"))
    else:
        return f"<h2>❌ Erreur lors de la publication :</h2><pre>{post_resp.text}</pre><p><a href='/dashboard'>Retour</a></p>"

@app.route("/profil")
def profil():
    if 'profile' not in session:
        return redirect(url_for("index"))
    return render_template("profil.html", **session['profile'])

@app.route("/historique")
def historique():
    if 'profile' not in session:
        return redirect(url_for("index"))

    access_token = session.get("access_token")
    sub = session["profile"].get("sub", "")
    user_id = sub.split("_")[-1]
    urn = f"urn:li:person:{user_id}"

    headers = {"Authorization": f"Bearer {access_token}"}
    posts_url = f"https://api.linkedin.com/v2/ugcPosts?q=authors&authors=List({urn})&sortBy=LAST_MODIFIED&count=10"

    try:
        response = requests.get(posts_url, headers=headers)
        if response.status_code != 200:
            return f"<p>Erreur récupération posts : {response.text}</p>"

        posts = response.json().get("elements", [])
        extracted_posts = []
        for post in posts:
            text = post.get("specificContent", {}).get("com.linkedin.ugc.ShareContent", {}).get("shareCommentary", {}).get("text", "")
            extracted_posts.append(text)

        return render_template("historique.html", posts=extracted_posts)

    except Exception as e:
        return f"<p>Exception lors de la récupération des posts : {str(e)}</p>"


@app.route("/parametres")
def parametres():
    if 'profile' not in session:
        return redirect(url_for("index"))
    return render_template("parametres.html")

@app.route("/calendar")
def calendar():
    if 'profile' not in session:
        return redirect(url_for("index"))
    return render_template("calendar.html")

@app.route("/logout")
def logout():
    session.clear()
    resp = make_response(redirect("/"))
    resp.set_cookie('linkedin_session', '', expires=0)
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

if __name__ == "__main__":
    app.run(debug=True, port=5000)
