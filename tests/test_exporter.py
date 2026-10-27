"""Tests for the exporter module (unit tests, no network calls)."""
import pytest
import zipfile
import io
from exporter import (
    escape_xml,
    sanitize_filename,
    _sanitize_folder_name,
    save_to_zip,
    build_track_filename,
    ExportError,
    KomootApi,
    ERROR_MESSAGES,
)


class TestEscapeXml:
    def test_ampersand(self):
        assert escape_xml('a & b') == 'a &amp; b'

    def test_less_than(self):
        assert escape_xml('a < b') == 'a &lt; b'

    def test_greater_than(self):
        assert escape_xml('a > b') == 'a &gt; b'

    def test_double_quote(self):
        assert escape_xml('a "b"') == 'a &quot;b&quot;'

    def test_single_quote(self):
        assert escape_xml("a 'b'") == "a &apos;b&apos;"

    def test_combined(self):
        assert escape_xml('<a & "b">') == '&lt;a &amp; &quot;b&quot;&gt;'

    def test_no_special_chars(self):
        assert escape_xml('hello world') == 'hello world'


class TestSanitizeFilename:
    def test_removes_slashes(self):
        assert '/' not in sanitize_filename('path/to/file')

    def test_removes_special_chars(self):
        result = sanitize_filename('file<>:"/\\|?*name')
        for c in '<>:"/\\|?*':
            assert c not in result

    def test_truncates_long_names(self):
        long_name = 'a' * 300
        assert len(sanitize_filename(long_name)) <= 200

    def test_normal_name_unchanged(self):
        assert sanitize_filename('My Tour 2024-01-01') == 'My Tour 2024-01-01'


class TestSanitizeFolderName:
    def test_removes_path_separators(self):
        result = _sanitize_folder_name('../../etc/passwd')
        assert '/' not in result
        assert '\\' not in result
        assert '..' not in result

    def test_empty_string(self):
        assert _sanitize_folder_name('') == ''

    def test_none(self):
        assert _sanitize_folder_name(None) == ''

    def test_strips_dots(self):
        result = _sanitize_folder_name('...folder...')
        assert not result.startswith('.')
        assert not result.endswith('.')

    def test_truncates(self):
        long_name = 'x' * 200
        assert len(_sanitize_folder_name(long_name)) <= 100


class TestExportError:
    def test_english_message(self):
        err = ExportError('login_failed', lang='en')
        assert 'Login failed' in str(err)

    def test_german_message(self):
        err = ExportError('login_failed', lang='de')
        assert 'fehlgeschlagen' in str(err)

    def test_with_details(self):
        err = ExportError('s3_connection_failed', details='timeout', lang='en')
        assert 'timeout' in str(err)

    def test_unknown_key_uses_key_as_message(self):
        err = ExportError('unknown_error_key', lang='en')
        assert 'unknown_error_key' in str(err)

    def test_all_error_keys_have_both_languages(self):
        for key, translations in ERROR_MESSAGES.items():
            assert 'en' in translations, f"Missing English for {key}"
            assert 'de' in translations, f"Missing German for {key}"


class TestSaveToZip:
    def test_creates_valid_zip(self):
        tracks = [
            {'name': 'Tour 1', 'gpx_data': '<gpx>data1</gpx>'},
            {'name': 'Tour 2', 'gpx_data': '<gpx>data2</gpx>'},
        ]
        result = save_to_zip(tracks)
        assert isinstance(result, bytes)

        zf = zipfile.ZipFile(io.BytesIO(result))
        names = zf.namelist()
        assert len(names) == 2
        assert 'Tour 1.gpx' in names
        assert 'Tour 2.gpx' in names

    def test_zip_with_folder(self):
        tracks = [{'name': 'My Tour', 'gpx_data': '<gpx>data</gpx>'}]
        result = save_to_zip(tracks, folder_name='exports')
        zf = zipfile.ZipFile(io.BytesIO(result))
        names = zf.namelist()
        assert names[0].startswith('exports/')

    def test_zip_content_correct(self):
        tracks = [{'name': 'Test', 'gpx_data': '<?xml version="1.0"?><gpx/>'}]
        result = save_to_zip(tracks)
        zf = zipfile.ZipFile(io.BytesIO(result))
        content = zf.read('Test.gpx').decode('utf-8')
        assert content == '<?xml version="1.0"?><gpx/>'

    def test_empty_tracks(self):
        result = save_to_zip([])
        zf = zipfile.ZipFile(io.BytesIO(result))
        assert len(zf.namelist()) == 0


class TestKomootApiGpxGeneration:
    def test_generate_gpx_basic(self):
        api = KomootApi()
        tour = {
            'name': 'Test Tour',
            '_embedded': {
                'coordinates': {
                    'items': [
                        {'lat': 48.1351, 'lng': 11.5820, 'alt': 520, 't': 1704067200000},
                        {'lat': 48.1352, 'lng': 11.5821, 'alt': 521, 't': 1704067260000},
                    ]
                }
            }
        }
        gpx = api.generate_gpx(tour)
        assert '<?xml version="1.0"' in gpx
        assert '<gpx' in gpx
        assert '</gpx>' in gpx
        assert '<name>Test Tour</name>' in gpx
        assert '<trkpt lat="48.1351" lon="11.582">' in gpx

    def test_generate_gpx_escapes_xml_in_name(self):
        api = KomootApi()
        tour = {
            'name': 'Tour & Run <2024>',
            '_embedded': {'coordinates': {'items': []}}
        }
        gpx = api.generate_gpx(tour)
        assert '&amp;' in gpx
        assert '&lt;' in gpx
        assert '&gt;' in gpx

    def test_generate_gpx_empty_coordinates(self):
        api = KomootApi()
        tour = {
            'name': 'Empty Tour',
            '_embedded': {'coordinates': {'items': []}}
        }
        gpx = api.generate_gpx(tour)
        assert '<trkseg>' in gpx
        assert '</trkseg>' in gpx
        assert '<trkpt' not in gpx


class TestBuildTrackFilename:
    def test_komoot_format_default(self):
        tour = {'id': 522280330, 'name': 'Tour', 'date': '2019-08-14T10:12:00.000+02:00'}
        assert build_track_filename(tour) == '2019-08-14_522280330_Tour'

    def test_simple_uses_name_only(self):
        tour = {'id': 522280330, 'name': 'Tour', 'date': '2019-08-14T10:12:00.000+02:00'}
        assert build_track_filename(tour, simple=True) == 'Tour'

    def test_missing_date(self):
        tour = {'id': 1, 'name': 'Tour'}
        assert build_track_filename(tour) == '1_Tour'

    def test_same_names_are_unique(self):
        a = {'id': 1, 'name': 'Wanderung', 'date': '2024-05-01T08:00:00Z'}
        b = {'id': 2, 'name': 'Wanderung', 'date': '2024-05-01T15:00:00Z'}
        assert build_track_filename(a) != build_track_filename(b)


class TestTrackFilenameInStorage:
    def test_zip_uses_filename(self):
        tracks = [
            {'name': 'Tour', 'filename': '2024-05-01_1_Tour', 'gpx_data': '<gpx>1</gpx>'},
            {'name': 'Tour', 'filename': '2024-05-02_2_Tour', 'gpx_data': '<gpx>2</gpx>'},
        ]
        zf = zipfile.ZipFile(io.BytesIO(save_to_zip(tracks)))
        assert sorted(zf.namelist()) == ['2024-05-01_1_Tour.gpx', '2024-05-02_2_Tour.gpx']

    def test_filename_is_sanitized(self):
        tracks = [{'name': 'a/b', 'filename': '2024-05-01_1_a/b', 'gpx_data': '<gpx/>'}]
        zf = zipfile.ZipFile(io.BytesIO(save_to_zip(tracks)))
        assert zf.namelist() == ['2024-05-01_1_a_b.gpx']

    def test_nfs_same_names_not_overwritten(self, tmp_path):
        from exporter import save_to_nfs
        tracks = [
            {'name': 'Tour', 'filename': '2024-05-01_1_Tour', 'gpx_data': '<gpx>1</gpx>'},
            {'name': 'Tour', 'filename': '2024-05-02_2_Tour', 'gpx_data': '<gpx>2</gpx>'},
        ]
        save_to_nfs(str(tmp_path), tracks)
        assert sorted(p.name for p in tmp_path.iterdir()) == ['2024-05-01_1_Tour.gpx', '2024-05-02_2_Tour.gpx']


class TestFetchKomootTracksFilenames:
    def _run(self, monkeypatch, simple):
        from datetime import datetime
        import exporter
        tours = [
            {'id': 1, 'name': 'Tour', 'date': '2024-05-01T08:00:00.000+02:00', 'type': 'tour_recorded', 'sport': 'hike'},
            {'id': 2, 'name': 'Tour', 'date': '2024-05-02T08:00:00.000+02:00', 'type': 'tour_recorded', 'sport': 'hike'},
        ]
        monkeypatch.setattr(exporter.KomootApi, 'login', lambda self, e, p, lang='en': None)
        monkeypatch.setattr(exporter.KomootApi, 'fetch_tours', lambda self, page=0: tours if page == 0 else [])
        monkeypatch.setattr(exporter.KomootApi, 'fetch_detailed_tour', lambda self, tid: {'name': 'Tour'})
        return exporter.fetch_komoot_tracks(datetime(2024, 1, 1), datetime(2024, 12, 31), False, '',
                                            'a@b.de:pw', simple_filenames=simple)

    def test_default_unique(self, monkeypatch):
        tracks = self._run(monkeypatch, False)
        assert [t['filename'] for t in tracks] == ['2024-05-01_1_Tour', '2024-05-02_2_Tour']

    def test_simple(self, monkeypatch):
        tracks = self._run(monkeypatch, True)
        assert [t['filename'] for t in tracks] == ['Tour', 'Tour']
