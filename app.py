from flask import Flask, render_template, request, jsonify, make_response
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
from exporter import export_tracks
from gevent.pywsgi import WSGIServer
from translations import get_translations, detect_language, TRANSLATIONS

__version__ = "v0.2.0"

HOST = os.environ.get('HOST', '0.0.0.0')
PORT = int(os.environ.get('PORT', 5000))
DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
SELF_HOSTED = os.environ.get('SELF_HOSTED', 'false').lower() == 'true'

# Rate limiting: 10 exports per hour per IP
RATE_LIMIT = os.environ.get('RATE_LIMIT', '10 per hour')

app = Flask(__name__)
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)


@app.route('/set-language/<lang>')
def set_language(lang):
    """Set language preference via cookie"""
    if lang not in TRANSLATIONS:
        lang = 'en'
    redirect_url = request.referrer or '/'
    response = make_response('', 302)
    response.headers['Location'] = redirect_url
    response.set_cookie('lang', lang, max_age=365*24*60*60)
    return response


@app.route('/')
def landing():
    """Landing page with feature overview"""
    lang = detect_language(request)
    t = get_translations(lang)
    other_lang = 'de' if lang == 'en' else 'en'
    other_t = get_translations(other_lang)
    return render_template('landing.html', 
                         self_hosted=SELF_HOSTED,
                         t=t,
                         other_lang=other_lang,
                         other_flag=other_t['flag'],
                         other_name=other_t['lang_name'])


@app.route('/export', methods=['GET', 'POST'])
@limiter.limit(RATE_LIMIT, methods=['POST'])
def export_page():
    if request.method == 'POST':
        # Detect language for error messages
        lang = detect_language(request)
        
        storage_type = request.form.get('storage_type', 's3')
        
        config = {
            'export_name': request.form.get('export_name', ''),
            'start_date': request.form.get('start_date'),
            'end_date': request.form.get('end_date'),
            'complete_only': request.form.get('complete_only') == 'on',
            'exercise_type': request.form.get('exercise_type', ''),
            'komoot_api_key': request.form.get('komoot_api_key'),
            'storage_type': storage_type,
        }
        
        if storage_type == 's3':
            config.update({
                's3_endpoint': request.form.get('s3_endpoint'),
                's3_bucket': request.form.get('s3_bucket'),
                's3_access_key': request.form.get('s3_access_key'),
                's3_secret_key': request.form.get('s3_secret_key'),
            })
        elif storage_type == 'nfs':
            config.update({
                'nfs_path': request.form.get('nfs_path'),
            })
        elif storage_type == 'smb':
            config.update({
                'smb_server': request.form.get('smb_server'),
                'smb_share': request.form.get('smb_share'),
                'smb_username': request.form.get('smb_username'),
                'smb_password': request.form.get('smb_password'),
                'smb_path': request.form.get('smb_path', ''),
            })
        
        try:
            result = export_tracks(config, lang=lang)
            return jsonify({'status': 'success', 'message': result})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)})
    else:
        lang = detect_language(request)
        t = get_translations(lang)
        other_lang = 'de' if lang == 'en' else 'en'
        other_t = get_translations(other_lang)
        return render_template('index.html', 
                             self_hosted=SELF_HOSTED,
                             t=t,
                             other_lang=other_lang,
                             other_flag=other_t['flag'],
                             other_name=other_t['lang_name'])


@app.route('/api/export', methods=['POST'])
@limiter.limit(RATE_LIMIT)
def api_export():
    """API endpoint for programmatic exports"""
    try:
        # Detect language from Accept-Language header for error messages
        lang = detect_language(request)
        
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'message': 'No JSON data provided'}), 400
        
        required_fields = ['start_date', 'end_date', 'komoot_api_key', 'storage_type']
        missing = [f for f in required_fields if not data.get(f)]
        if missing:
            return jsonify({'status': 'error', 'message': f'Missing required fields: {", ".join(missing)}'}), 400
        
        result = export_tracks(data, lang=lang)
        return jsonify({'status': 'success', 'message': result})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api', methods=['GET'])
def api_docs():
    """API documentation page"""
    lang = detect_language(request)
    t = get_translations(lang)
    other_lang = 'de' if lang == 'en' else 'en'
    other_t = get_translations(other_lang)
    return render_template('api.html',
                         t=t,
                         other_lang=other_lang,
                         other_flag=other_t['flag'],
                         other_name=other_t['lang_name'],
                         rate_limit=RATE_LIMIT)


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'version': __version__})


if __name__ == '__main__':
    print(f"Starting Komoot to Storage Exporter {__version__}")
    print(f"Listening on {HOST}:{PORT}")
    if DEBUG:
        app.run(host=HOST, port=PORT, debug=DEBUG)
    else:
        http_server = WSGIServer((HOST, PORT), app)
        http_server.serve_forever()
