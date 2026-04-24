from flask import Flask
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from dotenv import load_dotenv
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env', override=True)

def create_app():
    app = Flask(__name__)
    CORS(app)

    app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'elibrary-super-secret-key-2024')
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = 86400  # 24 hours

    JWTManager(app)

    from routes.auth import auth_bp
    from routes.papers import papers_bp
    from routes.users import users_bp
    from routes.admin import admin_bp
    from routes.recommendations import rec_bp

    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(papers_bp, url_prefix='/api/papers')
    app.register_blueprint(users_bp, url_prefix='/api/users')
    app.register_blueprint(admin_bp, url_prefix='/api/admin')
    app.register_blueprint(rec_bp, url_prefix='/api/recommendations')

    # Serve frontend
    from flask import render_template
    @app.route('/')
    @app.route('/<path:path>')
    def index(path=''):
        return render_template('index.html')

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, port=5000)
