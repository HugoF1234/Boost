import gradio as gr
import requests

def get_linkedin_userinfo(access_token):
    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    # 1. Récupération du profil via /v2/userinfo
    url = "https://api.linkedin.com/v2/userinfo"
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        return f"❌ Erreur : {response.status_code} - {response.text}", None

    data = response.json()

    full_name = data.get("name", "Nom inconnu")
    email = data.get("email", "Email inconnu")
    picture = data.get("picture", None)

    md = f"""
# 👤 Profil LinkedIn (via OpenID)
- **Nom complet** : {full_name}
- **Email** : {email}
- **ID LinkedIn** : `{data.get("sub", "?"[:10])}`
"""

    return md, picture

# Interface Gradio
demo = gr.Interface(
    fn=get_linkedin_userinfo,
    inputs=gr.Textbox(label="🔐 Access Token OAuth2 LinkedIn", lines=1, type="password"),
    outputs=[
        gr.Markdown(label="📋 Résumé utilisateur"),
        gr.Image(label="🖼️ Photo de profil")
    ],
    title="🔎 LinkedIn UserInfo via OpenID Connect",
    description="Collez votre token d'accès OAuth2 (scopes openid, profile, email) pour voir votre profil simplifié."
)

demo.launch()
