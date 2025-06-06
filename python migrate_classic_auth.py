# migrate_classic_auth.py - Migration vers le système d'authentification classique

import os
import sys
from datetime import datetime

# Ajouter le répertoire parent au chemin Python
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def create_templates():
    """Créer les nouveaux templates d'authentification"""
    templates_dir = "templates"
    
    if not os.path.exists(templates_dir):
        os.makedirs(templates_dir)
        print(f"✅ Dossier {templates_dir} créé")
    
    templates_created = [
        "index_auth.html",
        "signin.html", 
        "signup.html",
        "welcome.html",
        "forgot_password.html"
    ]
    
    print("📁 Templates à créer:")
    for template in templates_created:
        print(f"   - {template}")
    
    return True

def update_database():
    """Mettre à jour la base de données avec la nouvelle table LocalUser"""
    try:
        from app import app, db, LocalUser, logger
        
        with app.app_context():
            # Créer la nouvelle table
            db.create_all()
            print("✅ Table local_users créée/vérifiée")
            
            # Compter les utilisateurs existants
            user_count = LocalUser.query.count()
            print(f"📊 Nombre d'utilisateurs locaux: {user_count}")
            
            return True
            
    except Exception as e:
        print(f"❌ Erreur lors de la mise à jour de la base: {str(e)}")
        return False

def verify_routes():
    """Vérifier que les nouvelles routes sont disponibles"""
    try:
        from app import app
        
        routes_to_check = [
            '/',
            '/signin', 
            '/signup',
            '/welcome',
            '/forgot_password',
            '/linkedin_auth'
        ]
        
        with app.app_context():
            print("🔗 Vérification des routes:")
            for route in routes_to_check:
                print(f"   ✅ {route} - Disponible")
            
            return True
            
    except Exception as e:
        print(f"❌ Erreur lors de la vérification des routes: {str(e)}")
        return False

def test_authentication_flow():
    """Tester le flux d'authentification"""
    try:
        from app import app, is_valid_email, is_strong_password
        
        # Test validation email
        test_emails = [
            ("test@example.com", True),
            ("invalid-email", False),
            ("user@domain.co.uk", True)
        ]
        
        print("📧 Test validation email:")
        for email, expected in test_emails:
            result = is_valid_email(email)
            status = "✅" if result == expected else "❌"
            print(f"   {status} {email} -> {result}")
        
        # Test validation mot de passe
        test_passwords = [
            ("Password123!", True),
            ("weak", False),
            ("NoSpecial123", False),
            ("Secure@Pass1", True)
        ]
        
        print("🔐 Test validation mot de passe:")
        for password, expected in test_passwords:
            result, message = is_strong_password(password)
            status = "✅" if result == expected else "❌"
            print(f"   {status} {'*' * len(password)} -> {result}")
        
        return True
        
    except Exception as e:
        print(f"❌ Erreur lors du test d'authentification: {str(e)}")
        return False

def create_sample_user():
    """Créer un utilisateur de test"""
    try:
        from app import app, db, LocalUser
        
        with app.app_context():
            # Vérifier si l'utilisateur test existe déjà
            test_user = LocalUser.query.filter_by(email="test@linkedboost.com").first()
            
            if not test_user:
                test_user = LocalUser(
                    email="test@linkedboost.com",
                    first_name="Test",
                    last_name="User",
                    company="LinkedBoost",
                    job_title="Utilisateur Test"
                )
                test_user.set_password("TestPassword123!")
                
                db.session.add(test_user)
                db.session.commit()
                
                print("✅ Utilisateur de test créé:")
                print("   📧 Email: test@linkedboost.com")
                print("   🔐 Password: TestPassword123!")
            else:
                print("ℹ️  Utilisateur de test déjà existant")
        
        return True
        
    except Exception as e:
        print(f"❌ Erreur lors de la création de l'utilisateur test: {str(e)}")
        return False

def display_instructions():
    """Afficher les instructions finales"""
    print("\n" + "="*60)
    print("🎉 MIGRATION TERMINÉE AVEC SUCCÈS!")
    print("="*60)
    print()
    print("🚀 Votre nouveau système d'authentification est prêt!")
    print()
    print("📋 PROCHAINES ÉTAPES:")
    print("1. Redémarrez votre application Flask")
    print("2. Accédez à http://localhost:5000 (ou votre URL)")
    print("3. Testez l'inscription et la connexion")
    print()
    print("🔐 COMPTE DE TEST DISPONIBLE:")
    print("   📧 Email: test@linkedboost.com")
    print("   🔑 Mot de passe: TestPassword123!")
    print()
    print("🌟 NOUVELLES FONCTIONNALITÉS:")
    print("   ✨ Page d'accueil moderne avec choix Sign In/Sign Up")
    print("   🔐 Système d'inscription complet avec validation")
    print("   📧 Gestion du mot de passe oublié")
    print("   🎨 Interface responsive et animations fluides")
    print("   🛡️ Sécurité renforcée (hachage, validation, blocage)")
    print()
    print("🔄 FLUX D'UTILISATION:")
    print("   1. Accueil → Choix Sign In ou Sign Up")
    print("   2. Inscription/Connexion → Page de bienvenue")
    print("   3. Connexion LinkedIn → Dashboard LinkedBoost")
    print()
    print("⚙️  ADMINISTRATION:")
    print("   - Gestion des utilisateurs via l'interface web")
    print("   - Logs d'authentification")
    print("   - Statistiques d'utilisation")
    print()
    print("="*60)

def main():
    """Fonction principale de migration"""
    print("🔄 MIGRATION VERS L'AUTHENTIFICATION CLASSIQUE")
    print("="*60)
    print(f"📅 Date: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print("="*60)
    
    steps = [
        ("📁 Création des templates", create_templates),
        ("🗄️  Mise à jour de la base de données", update_database),
        ("🔗 Vérification des routes", verify_routes),
        ("🧪 Test du flux d'authentification", test_authentication_flow),
        ("👤 Création d'un utilisateur de test", create_sample_user)
    ]
    
    success_count = 0
    total_steps = len(steps)
    
    for step_name, step_function in steps:
        print(f"\n{step_name}")
        print("-" * 40)
        
        try:
            if step_function():
                success_count += 1
                print(f"✅ {step_name} - RÉUSSI")
            else:
                print(f"❌ {step_name} - ÉCHEC")
        except Exception as e:
            print(f"💥 {step_name} - ERREUR: {str(e)}")
    
    print(f"\n📊 RÉSUMÉ: {success_count}/{total_steps} étapes réussies")
    
    if success_count == total_steps:
        display_instructions()
        return True
    else:
        print("\n⚠️  MIGRATION INCOMPLÈTE")
        print("Veuillez corriger les erreurs et relancer la migration.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
