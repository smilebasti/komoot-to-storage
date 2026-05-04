from flask import Flask, render_template, request, jsonify, make_response, Response, abort, g
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
import re
import signal
import uuid
import logging
from datetime import datetime
from exporter import export_tracks
from gevent.pywsgi import WSGIServer
from translations import get_translations, detect_language, TRANSLATIONS

__version__ = "v1.3.2"

# Configure logging
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

HOST = os.environ.get('HOST', '0.0.0.0')
PORT = int(os.environ.get('PORT', 5000))
DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
SELF_HOSTED = os.environ.get('SELF_HOSTED', 'false').lower() == 'true'

# Rate limiting: 10 exports per hour per IP
RATE_LIMIT = os.environ.get('RATE_LIMIT', '10 per hour')

# Maximum date range in days (prevent abuse via huge ranges)
MAX_DATE_RANGE_DAYS = int(os.environ.get('MAX_DATE_RANGE_DAYS', '3650'))

app = Flask(__name__)
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)


# -------------------------------------------------------------------------
# Request ID tracking
# -------------------------------------------------------------------------
@app.before_request
def assign_request_id():
    """Assign a unique request ID for log correlation."""
    g.request_id = request.headers.get('X-Request-ID', uuid.uuid4().hex[:12])


# -------------------------------------------------------------------------
# Security headers
# -------------------------------------------------------------------------
@app.after_request
def set_security_headers(response):
    """Add security headers to every response."""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    # CSP: allow Bootstrap CDN and inline styles/scripts used by templates
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "font-src 'self' https://cdn.jsdelivr.net; "
        "img-src 'self' data:; "
        "frame-ancestors 'none';"
    )
    # Echo request ID in response header for debugging
    request_id = getattr(g, 'request_id', None)
    if request_id:
        response.headers['X-Request-ID'] = request_id
    return response


# -------------------------------------------------------------------------
# Input validation helpers
# -------------------------------------------------------------------------
_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _validate_date(value: str, field_name: str) -> datetime:
    """Validate and parse a YYYY-MM-DD date string."""
    if not value or not _DATE_RE.match(value):
        raise ValueError(f"Invalid {field_name}: expected YYYY-MM-DD format")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"Invalid {field_name}: not a valid calendar date")


def _validate_date_range(start_str: str, end_str: str):
    """Validate start/end dates and return parsed datetimes."""
    start = _validate_date(start_str, 'start_date')
    end = _validate_date(end_str, 'end_date')
    if start > end:
        raise ValueError("start_date must be before or equal to end_date")
    if (end - start).days > MAX_DATE_RANGE_DAYS:
        raise ValueError(f"Date range must not exceed {MAX_DATE_RANGE_DAYS} days")
    return start, end


def _validate_credentials(email: str, password: str):
    """Basic sanity check on Komoot credentials."""
    if not email or not password:
        raise ValueError("Komoot email and password are required")
    if not _EMAIL_RE.match(email):
        raise ValueError("Invalid email address format")
    if len(password) < 1 or len(password) > 500:
        raise ValueError("Invalid password length")


def _validate_storage_config(storage_type: str, config: dict):
    """Validate that required storage fields are present and non-empty."""
    required = {
        's3': ['s3_endpoint', 's3_bucket', 's3_access_key', 's3_secret_key'],
        'nfs': ['nfs_path'],
        'smb': ['smb_server', 'smb_share', 'smb_username', 'smb_password'],
        'webdav': ['webdav_url', 'webdav_username', 'webdav_password'],
        'download': [],
    }
    fields = required.get(storage_type)
    if fields is None:
        raise ValueError(f"Unknown storage type: {storage_type}")
    missing = [f for f in fields if not config.get(f)]
    if missing:
        raise ValueError(f"Missing required fields for {storage_type}: {', '.join(missing)}")
    # NFS only allowed in self-hosted mode
    if storage_type == 'nfs' and not SELF_HOSTED:
        raise ValueError("NFS storage is only available in self-hosted mode")


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
        
        # --- Input validation ---
        try:
            start_date_str = (request.form.get('start_date') or '').strip()
            end_date_str = (request.form.get('end_date') or '').strip()
            _validate_date_range(start_date_str, end_date_str)
            
            api_key = (request.form.get('komoot_api_key') or '').strip()
            if ':' in api_key:
                email_part, pass_part = api_key.split(':', 1)
                _validate_credentials(email_part, pass_part)
        except ValueError as e:
            logger.warning("Validation error: %s", str(e))
            return jsonify({'status': 'error', 'message': str(e)}), 400
        
        config = {
            'export_name': request.form.get('export_name', ''),
            'start_date': start_date_str,
            'end_date': end_date_str,
            'complete_only': request.form.get('complete_only') == 'on',
            'exercise_type': request.form.get('exercise_type', ''),
            'komoot_api_key': api_key,
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
        elif storage_type == 'webdav':
            config.update({
                'webdav_url': request.form.get('webdav_url'),
                'webdav_username': request.form.get('webdav_username'),
                'webdav_password': request.form.get('webdav_password'),
                'webdav_path': request.form.get('webdav_path', ''),
            })
        
        # Validate storage configuration
        try:
            _validate_storage_config(storage_type, config)
        except ValueError as e:
            logger.warning("Storage validation error: %s", str(e))
            return jsonify({'status': 'error', 'message': str(e)}), 400
        
        try:
            logger.info("[%s] Export request: storage=%s, dates=%s to %s, type=%s",
                       g.request_id, storage_type, config.get('start_date'), config.get('end_date'),
                       config.get('exercise_type') or 'all')
            result = export_tracks(config, lang=lang)
            # Download mode returns bytes (ZIP file)
            if storage_type == 'download' and isinstance(result, bytes):
                zip_name = config.get('export_name', 'komoot-export') or 'komoot-export'
                zip_name = zip_name.strip() or 'komoot-export'
                logger.info("[%s] Export download completed: %s.zip (%d bytes)", g.request_id, zip_name, len(result))
                return Response(
                    result,
                    mimetype='application/zip',
                    headers={'Content-Disposition': f'attachment; filename="{zip_name}.zip"'}
                )
            logger.info("[%s] Export completed: %s", g.request_id, result)
            return jsonify({'status': 'success', 'message': result})
        except Exception as e:
            logger.warning("[%s] Export failed: %s", g.request_id, str(e))
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
        
        # Validate dates
        try:
            _validate_date_range(data['start_date'], data['end_date'])
        except ValueError as e:
            return jsonify({'status': 'error', 'message': str(e)}), 400
        
        # Validate credentials format
        api_key = data.get('komoot_api_key', '')
        if ':' in api_key:
            email_part, pass_part = api_key.split(':', 1)
            try:
                _validate_credentials(email_part, pass_part)
            except ValueError as e:
                return jsonify({'status': 'error', 'message': str(e)}), 400
        
        # Validate storage config
        try:
            _validate_storage_config(data.get('storage_type', ''), data)
        except ValueError as e:
            return jsonify({'status': 'error', 'message': str(e)}), 400
        
        # Download mode not supported via API (returns binary data)
        if data.get('storage_type') == 'download':
            return jsonify({'status': 'error', 'message': 'Download mode is not supported via the API. Use the web interface or choose a storage backend.'}), 400
        
        logger.info("[%s] API export request: storage=%s, dates=%s to %s",
                   g.request_id, data.get('storage_type'), data.get('start_date'), data.get('end_date'))
        result = export_tracks(data, lang=lang)
        logger.info("[%s] API export completed: %s", g.request_id, result)
        return jsonify({'status': 'success', 'message': result})
    except ValueError as e:
        logger.warning("[%s] API validation error: %s", g.request_id, str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 400
    except Exception as e:
        logger.warning("[%s] API export failed: %s", g.request_id, str(e))
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


@app.route('/robots.txt')
def robots():
    """Serve robots.txt to prevent search engine crawling of export endpoints"""
    content = "User-agent: *\nDisallow: /export\nDisallow: /api/\nAllow: /\n"
    return Response(content, mimetype='text/plain')


@app.errorhandler(404)
def not_found(e):
    """Custom 404 handler"""
    if request.path.startswith('/api/'):
        return jsonify({'status': 'error', 'message': 'Endpoint not found'}), 404
    lang = detect_language(request)
    t = get_translations(lang)
    return render_template('landing.html',
                         self_hosted=SELF_HOSTED,
                         t=t,
                         other_lang='de' if lang == 'en' else 'en',
                         other_flag=get_translations('de' if lang == 'en' else 'en')['flag'],
                         other_name=get_translations('de' if lang == 'en' else 'en')['lang_name']), 404


@app.errorhandler(429)
def ratelimit_handler(e):
    """Custom rate limit exceeded handler"""
    if request.path.startswith('/api/'):
        return jsonify({
            'status': 'error',
            'message': 'Rate limit exceeded. Please try again later.',
            'retry_after': e.description
        }), 429
    return jsonify({'status': 'error', 'message': str(e.description)}), 429


@app.errorhandler(500)
def internal_error(e):
    """Custom 500 handler"""
    logger.error("Internal server error: %s", str(e))
    if request.path.startswith('/api/'):
        return jsonify({'status': 'error', 'message': 'Internal server error'}), 500
    return jsonify({'status': 'error', 'message': 'An unexpected error occurred'}), 500


if __name__ == '__main__':
    logger.info("Starting Komoot to Storage Exporter %s", __version__)
    logger.info("Listening on %s:%d (self_hosted=%s)", HOST, PORT, SELF_HOSTED)
    if DEBUG:
        app.run(host=HOST, port=PORT, debug=DEBUG)
    else:
        http_server = WSGIServer((HOST, PORT), app)

        def _graceful_shutdown(signum, frame):
            sig_name = signal.Signals(signum).name
            logger.info("Received %s — shutting down gracefully …", sig_name)
            http_server.stop(timeout=10)

        signal.signal(signal.SIGTERM, _graceful_shutdown)
        signal.signal(signal.SIGINT, _graceful_shutdown)

        http_server.serve_forever()
