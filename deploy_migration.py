#!/usr/bin/env python3
"""
Script de déploiement pour Render - Migre la base PostgreSQL
Ce script doit être exécuté sur Render après le déploiement
"""

import os
import sys
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

# Configuration de l'application
app = Flask(__name__)

# Configuration de la base de données PostgreSQL
db_url = os.getenv("DATABASE_URL")
if not db_url:
    print("❌ DATABASE_URL non définie")
    sys.exit(1)

# Pour Render, vérifier et corriger l'URL si nécessaire
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Modèle User
class User(db.Model):
    __tablename__ = 'users'
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
    interets = db.Column(db.JSON, default=list)

# Modèle Post avec tous les nouveaux champs
class Post(db.Model):
    __tablename__ = 'posts'
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    subject = db.Column(db.String(255))
    tone = db.Column(db.String(50))
    perspective = db.Column(db.String(50))
    status = db.Column(db.String(20), default="draft")  # draft / scheduled / published
    published_at = db.Column(db.DateTime, nullable=True)
    scheduled_at = db.Column(db.DateTime, nullable=True)
    linkedin_post_urn = db.Column(db.String(255), nullable=True)
    images = db.Column(db.Text)  # JSON contenant la liste des images
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    scheduled = db.Column(db.Boolean, default=False)  # Gardé pour compatibilité

def migrate_database():
    """Migre la base de données PostgreSQL vers le nouveau schéma"""
    try:
        print("🔄 Début de la migration PostgreSQL sur Render...")
        
        with app.app_context():
            # Vérifier les tables existantes
            from sqlalchemy import inspect
            inspector = inspect(db.engine)
            existing_tables = inspector.get_table_names()
            print(f"📋 Tables existantes: {existing_tables}")
            
            # Vérifier les colonnes de la table posts
            if 'posts' in existing_tables:
                columns = inspector.get_columns('posts')
                column_names = [col['name'] for col in columns]
                print(f"📋 Colonnes actuelles de posts: {column_names}")
                
                # Vérifier quelles colonnes manquent
                required_columns = ['subject', 'tone', 'perspective', 'status', 'scheduled_at', 'images', 'created_at']
                missing_columns = [col for col in required_columns if col not in column_names]
                
                if missing_columns:
                    print(f"⚠️ Colonnes manquantes: {missing_columns}")
                    print("🔄 Recréation des tables avec le nouveau schéma...")
                    
                    # Sauvegarder les données existantes
                    posts_data = []
                    try:
                        result = db.engine.execute("SELECT * FROM posts")
                        posts_data = [dict(row) for row in result]
                        print(f"💾 {len(posts_data)} posts sauvegardés")
                    except Exception as e:
                        print(f"⚠️ Impossible de sauvegarder les posts: {e}")
                    
                    # Supprimer et recréer les tables
                    print("🗑️ Suppression des anciennes tables...")
                    db.drop_all()
                    
                    print("🏗️ Création des nouvelles tables...")
                    db.create_all()
                    
                    # Restaurer les données si possible
                    if posts_data:
                        print("📥 Restauration des données...")
                        for post_data in posts_data:
                            try:
                                new_post = Post(
                                    id=post_data.get('id'),
                                    content=post_data.get('content', ''),
                                    subject=post_data.get('subject', ''),
                                    tone=post_data.get('tone', ''),
                                    perspective=post_data.get('perspective', ''),
                                    status=post_data.get('status', 'draft'),
                                    published_at=post_data.get('published_at'),
                                    scheduled_at=post_data.get('scheduled_at'),
                                    linkedin_post_urn=post_data.get('linkedin_post_urn'),
                                    images=post_data.get('images', '[]'),
                                    created_at=post_data.get('created_at', datetime.utcnow()),
                                    user_id=post_data.get('user_id'),
                                    scheduled=post_data.get('scheduled', False)
                                )
                                db.session.add(new_post)
                            except Exception as e:
                                print(f"⚠️ Erreur lors de la restauration du post {post_data.get('id')}: {e}")
                        
                        db.session.commit()
                        print("✅ Données restaurées avec succès")
                else:
                    print("✅ Toutes les colonnes requises sont déjà présentes")
            
            # Vérifier la migration finale
            new_tables = inspector.get_table_names()
            print(f"📋 Tables finales: {new_tables}")
            
            if 'posts' in new_tables:
                columns = inspector.get_columns('posts')
                column_names = [col['name'] for col in columns]
                print(f"📋 Colonnes finales de posts: {column_names}")
                
                # Vérifier que toutes les colonnes requises existent
                required_columns = ['subject', 'tone', 'perspective', 'status', 'scheduled_at', 'images', 'created_at']
                missing_columns = [col for col in required_columns if col not in column_names]
                
                if missing_columns:
                    print(f"❌ Colonnes manquantes après migration: {missing_columns}")
                    return False
                else:
                    print("✅ Migration terminée avec succès - toutes les colonnes sont présentes")
            
            print("🎉 Migration PostgreSQL sur Render terminée avec succès!")
            return True
            
    except Exception as e:
        print(f"❌ Erreur lors de la migration: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = migrate_database()
    sys.exit(0 if success else 1)
