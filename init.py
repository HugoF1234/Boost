# add_columns_user.py
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from urllib.parse import quote_plus

app = Flask(__name__)
password = quote_plus("Lexia2025")
app.config['SQLALCHEMY_DATABASE_URI'] = f'postgresql://user3:{password}@localhost:5432/Boostdb'
db = SQLAlchemy(app)

with app.app_context():
    try:
        db.session.execute(text("""
            ALTER TABLE "user" ADD COLUMN IF NOT EXISTS secteur TEXT;
        """))
        db.session.execute(text("""
            ALTER TABLE "user" ADD COLUMN IF NOT EXISTS interets TEXT[];
        """))
        db.session.commit()
        print("✅ Colonnes 'secteur' et 'interets' ajoutées avec succès.")
    except Exception as e:
        print(f"❌ Erreur : {e}")
