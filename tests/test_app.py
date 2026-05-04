"""Tests for Flask app routes and basic functionality."""
import json
import pytest
from app import app


@pytest.fixture
def client():
    """Create a test client."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        resp = client.get('/health')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'ok'
        assert 'version' in data

    def test_health_returns_json(self, client):
        resp = client.get('/health')
        assert resp.content_type.startswith('application/json')


class TestLandingPage:
    def test_landing_returns_200(self, client):
        resp = client.get('/')
        assert resp.status_code == 200

    def test_landing_contains_html(self, client):
        resp = client.get('/')
        assert b'<!DOCTYPE html>' in resp.data or b'<html' in resp.data


class TestExportPage:
    def test_export_get_returns_200(self, client):
        resp = client.get('/export')
        assert resp.status_code == 200

    def test_export_post_missing_fields(self, client):
        resp = client.post('/export', data={})
        # Should return 400 since empty form data fails validation
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['status'] == 'error'


class TestApiDocs:
    def test_api_docs_returns_200(self, client):
        resp = client.get('/api')
        assert resp.status_code == 200


class TestApiExport:
    def test_api_export_no_json(self, client):
        resp = client.post('/api/export', content_type='application/json')
        assert resp.status_code in (400, 500)
        data = resp.get_json()
        assert data['status'] == 'error'

    def test_api_export_missing_fields(self, client):
        resp = client.post('/api/export',
                           data=json.dumps({'start_date': '2024-01-01'}),
                           content_type='application/json')
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['status'] == 'error'
        assert 'Missing required fields' in data['message']

    def test_api_export_download_not_supported(self, client):
        resp = client.post('/api/export',
                           data=json.dumps({
                               'start_date': '2024-01-01',
                               'end_date': '2024-12-31',
                               'komoot_api_key': 'test@test.com:password',
                               'storage_type': 'download'
                           }),
                           content_type='application/json')
        assert resp.status_code == 400
        data = resp.get_json()
        assert 'Download mode' in data['message']

    def test_api_export_invalid_dates(self, client):
        resp = client.post('/api/export',
                           data=json.dumps({
                               'start_date': 'not-a-date',
                               'end_date': '2024-12-31',
                               'komoot_api_key': 'test@test.com:password',
                               'storage_type': 's3',
                               's3_endpoint': 'https://s3.example.com',
                               's3_bucket': 'test',
                               's3_access_key': 'key',
                               's3_secret_key': 'secret',
                           }),
                           content_type='application/json')
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['status'] == 'error'

    def test_api_export_start_after_end(self, client):
        resp = client.post('/api/export',
                           data=json.dumps({
                               'start_date': '2025-01-01',
                               'end_date': '2024-01-01',
                               'komoot_api_key': 'test@test.com:password',
                               'storage_type': 's3',
                               's3_endpoint': 'https://s3.example.com',
                               's3_bucket': 'test',
                               's3_access_key': 'key',
                               's3_secret_key': 'secret',
                           }),
                           content_type='application/json')
        assert resp.status_code == 400
        data = resp.get_json()
        assert 'before or equal' in data['message']

    def test_api_export_unknown_storage_type(self, client):
        resp = client.post('/api/export',
                           data=json.dumps({
                               'start_date': '2024-01-01',
                               'end_date': '2024-12-31',
                               'komoot_api_key': 'test@test.com:password',
                               'storage_type': 'ftp',
                           }),
                           content_type='application/json')
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['status'] == 'error'

    def test_api_export_invalid_email(self, client):
        resp = client.post('/api/export',
                           data=json.dumps({
                               'start_date': '2024-01-01',
                               'end_date': '2024-12-31',
                               'komoot_api_key': 'notanemail:password',
                               'storage_type': 's3',
                               's3_endpoint': 'https://s3.example.com',
                               's3_bucket': 'test',
                               's3_access_key': 'key',
                               's3_secret_key': 'secret',
                           }),
                           content_type='application/json')
        assert resp.status_code == 400
        data = resp.get_json()
        assert 'email' in data['message'].lower() or 'Invalid' in data['message']


class TestSetLanguage:
    def test_set_language_de(self, client):
        resp = client.get('/set-language/de', headers={'Referer': '/'})
        assert resp.status_code == 302
        set_cookie = resp.headers.get('Set-Cookie', '')
        assert 'lang=de' in set_cookie

    def test_set_language_invalid_falls_back_to_en(self, client):
        resp = client.get('/set-language/xx', headers={'Referer': '/'})
        assert resp.status_code == 302
        set_cookie = resp.headers.get('Set-Cookie', '')
        assert 'lang=en' in set_cookie

    def test_set_language_no_referer(self, client):
        resp = client.get('/set-language/en')
        assert resp.status_code == 302
        assert resp.headers['Location'] == '/'


class TestSecurityHeaders:
    def test_csp_header_present(self, client):
        resp = client.get('/health')
        assert 'Content-Security-Policy' in resp.headers

    def test_x_content_type_options(self, client):
        resp = client.get('/health')
        assert resp.headers['X-Content-Type-Options'] == 'nosniff'

    def test_x_frame_options(self, client):
        resp = client.get('/health')
        assert resp.headers['X-Frame-Options'] == 'DENY'

    def test_referrer_policy(self, client):
        resp = client.get('/health')
        assert resp.headers['Referrer-Policy'] == 'strict-origin-when-cross-origin'

    def test_permissions_policy(self, client):
        resp = client.get('/health')
        assert 'camera=()' in resp.headers['Permissions-Policy']


class TestRequestId:
    def test_response_has_request_id(self, client):
        resp = client.get('/health')
        assert 'X-Request-ID' in resp.headers

    def test_custom_request_id_echoed(self, client):
        resp = client.get('/health', headers={'X-Request-ID': 'test-req-123'})
        assert resp.headers['X-Request-ID'] == 'test-req-123'

    def test_generated_request_id_is_hex(self, client):
        resp = client.get('/health')
        rid = resp.headers['X-Request-ID']
        assert len(rid) == 12
        assert all(c in '0123456789abcdef' for c in rid)


class TestRobotsTxt:
    def test_robots_returns_200(self, client):
        resp = client.get('/robots.txt')
        assert resp.status_code == 200

    def test_robots_is_text(self, client):
        resp = client.get('/robots.txt')
        assert resp.content_type.startswith('text/plain')

    def test_robots_disallows_export(self, client):
        resp = client.get('/robots.txt')
        assert b'Disallow: /export' in resp.data

    def test_robots_disallows_api(self, client):
        resp = client.get('/robots.txt')
        assert b'Disallow: /api/' in resp.data


class TestErrorHandlers:
    def test_404_html(self, client):
        resp = client.get('/nonexistent-page')
        assert resp.status_code == 404

    def test_404_api_returns_json(self, client):
        resp = client.get('/api/nonexistent')
        assert resp.status_code == 404
        data = resp.get_json()
        assert data['status'] == 'error'
        assert 'not found' in data['message'].lower()


class TestInputValidation:
    def test_export_post_invalid_date_format(self, client):
        resp = client.post('/export', data={
            'start_date': '01-01-2024',
            'end_date': '2024-12-31',
            'komoot_api_key': 'test@test.com:pass',
            'storage_type': 's3',
        })
        assert resp.status_code == 400
        data = resp.get_json()
        assert 'Invalid' in data['message'] or 'format' in data['message']

    def test_export_post_date_range_exceeds_max(self, client):
        resp = client.post('/export', data={
            'start_date': '2010-01-01',
            'end_date': '2024-12-31',
            'komoot_api_key': 'test@test.com:pass',
            'storage_type': 's3',
        })
        assert resp.status_code == 400
        data = resp.get_json()
        assert 'exceed' in data['message'].lower() or 'range' in data['message'].lower()
