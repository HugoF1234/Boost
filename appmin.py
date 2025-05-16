from flask import Flask, jsonify
import os
import logging

# Configuration des logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/')
def index():
    """Page d'accueil simplifiée pour tester le déploiement"""
    logger.info("Accès à la page d'accueil")
    return jsonify({
        "status": "ok",
        "message": "Application LinkedIn Boost démarrée avec succès",
        "environment": os.environ.get("RENDER", "non défini"),
        "database_url": os.environ.get("DATABASE_URL", "non défini").replace(":", "[HIDDEN]")
    })

@app.route('/debug')
def debug():
    """Affiche des informations de débogage"""
    env_vars = {k: v.replace(":", "[HIDDEN]") if "DATABASE_URL" in k or "SECRET" in k or "KEY" in k else v 
                for k, v in os.environ.items()}
    return jsonify({
        "environment_variables": env_vars,
        "python_version": os.sys.version,
        "working_directory": os.getcwd(),
        "files_in_directory": os.listdir(os.getcwd()) if os.path.exists(os.getcwd()) else []
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
