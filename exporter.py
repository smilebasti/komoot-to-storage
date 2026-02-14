import requests
import boto3
import os
from datetime import datetime, timezone
import base64
import re
from typing import List, Dict, Any, Optional

# Optional SMB support
try:
    from smbprotocol.connection import Connection
    from smbprotocol.session import Session
    from smbprotocol.tree import TreeConnect
    from smbprotocol.open import Open, CreateDisposition, FileAttributes, ShareAccess, ImpersonationLevel
    from smbprotocol.file_info import FileInformationClass
    SMB_AVAILABLE = True
except ImportError:
    SMB_AVAILABLE = False


class KomootApi:
    def __init__(self):
        self.user_id = ""
        self.token = ""

    def login(self, email: str, password: str):
        """Login to Komoot API using email and password"""
        url = f"https://api.komoot.de/v006/account/email/{email}/"
        auth = base64.b64encode(f"{email}:{password}".encode()).decode()
        headers = {"Authorization": f"Basic {auth}"}

        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            raise Exception(f"Login failed: {response.status_code} - {response.text}")

        data = response.json()
        self.user_id = data.get("username")
        self.token = data.get("password")

    def fetch_tours(self, page: int = 0) -> List[Dict[str, Any]]:
        """Fetch tours from Komoot API"""
        if not self.user_id or not self.token:
            raise Exception("Not logged in")

        url = f"https://api.komoot.de/v007/users/{self.user_id}/tours/"
        params = {
            "page": page,
            "sort_field": "date",
            "sort_direction": "desc",
            "limit": 30
        }
        auth = base64.b64encode(f"{self.user_id}:{self.token}".encode()).decode()
        headers = {"Authorization": f"Basic {auth}"}

        response = requests.get(url, headers=headers, params=params)
        if response.status_code != 200:
            raise Exception(f"Failed to fetch tours: {response.status_code} - {response.text}")

        data = response.json()
        return data.get("_embedded", {}).get("tours", [])

    def fetch_detailed_tour(self, tour_id: int) -> Dict[str, Any]:
        """Fetch detailed tour information including coordinates"""
        if not self.user_id or not self.token:
            raise Exception("Not logged in")

        url = f"https://api.komoot.de/v007/tours/{tour_id}"
        params = {
            "_embedded": "coordinates,way_types,surfaces,directions,participants,timeline,cover_images",
            "directions": "v2",
            "fields": "timeline",
            "format": "coordinate_array",
            "timeline_highlights_fields": "tips,recommenders",
            "page": 2
        }
        auth = base64.b64encode(f"{self.user_id}:{self.token}".encode()).decode()
        headers = {"Authorization": f"Basic {auth}"}

        response = requests.get(url, headers=headers, params=params)
        if response.status_code != 200:
            raise Exception(f"Failed to fetch tour details: {response.status_code} - {response.text}")

        return response.json()

    def generate_gpx(self, tour: Dict[str, Any]) -> str:
        """Generate GPX data from tour coordinates"""
        gpx_header = '<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="Komoot GPX Exporter" xmlns="http://www.topografix.com/GPX/1/1" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd">\n'
        gpx_footer = '</gpx>'

        track_name = tour.get('name', 'Unknown Track')
        # Escape XML special characters in track name
        track_name = escape_xml(track_name)
        coordinates = tour.get('_embedded', {}).get('coordinates', {}).get('items', [])

        gpx_track = f'  <trk>\n    <name>{track_name}</name>\n    <trkseg>\n'

        for coord in coordinates:
            lat = coord.get('lat')
            lng = coord.get('lng')
            alt = coord.get('alt', 0)
            t = coord.get('t', 0)  # timestamp in milliseconds

            # Convert timestamp to ISO format
            timestamp = datetime.fromtimestamp(t / 1000).isoformat() + 'Z'

            gpx_track += f'      <trkpt lat="{lat}" lon="{lng}">\n        <ele>{alt}</ele>\n        <time>{timestamp}</time>\n      </trkpt>\n'

        gpx_track += '    </trkseg>\n  </trk>\n'

        return gpx_header + gpx_track + gpx_footer


def escape_xml(text: str) -> str:
    """Escape XML special characters"""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&apos;')


def sanitize_filename(name: str) -> str:
    """Sanitize a string to be safe as a filename"""
    # Remove or replace characters that are problematic in filenames
    safe_name = re.sub(r'[<>:"/\\|?*]', '_', name)
    safe_name = safe_name.replace('/', '_')
    return safe_name[:200]  # Limit length


def export_tracks(config: Dict[str, Any]) -> str:
    """Main export function that handles different storage backends"""
    # Validate required fields
    if not config.get('start_date') or not config.get('end_date'):
        raise ValueError("Start date and end date are required")
    
    if not config.get('komoot_api_key'):
        raise ValueError("Komoot credentials are required")

    # Convert date strings to datetime objects
    start_date = datetime.fromisoformat(config['start_date'])
    end_date = datetime.fromisoformat(config['end_date'])
    
    # Fetch tracks from Komoot
    tracks = fetch_komoot_tracks(
        start_date, 
        end_date, 
        config.get('complete_only', False), 
        config.get('exercise_type', ''), 
        config.get('komoot_api_key')
    )

    if not tracks:
        return "No tracks found matching the criteria."

    # Determine storage type and save
    storage_type = config.get('storage_type', 's3')
    folder_name = config.get('export_name', '')

    if storage_type == 's3':
        save_to_s3(
            config.get('s3_endpoint'),
            config.get('s3_bucket'),
            config.get('s3_access_key'),
            config.get('s3_secret_key'),
            tracks,
            folder_name
        )
        return f"Exported {len(tracks)} tracks to S3 storage."
    
    elif storage_type == 'nfs':
        save_to_nfs(
            config.get('nfs_path'),
            tracks,
            folder_name
        )
        return f"Exported {len(tracks)} tracks to NFS path."
    
    elif storage_type == 'smb':
        if not SMB_AVAILABLE:
            raise ImportError("SMB support requires smbprotocol. Install with: pip install smbprotocol")
        save_to_smb(
            config.get('smb_server'),
            config.get('smb_share'),
            config.get('smb_username'),
            config.get('smb_password'),
            config.get('smb_path', ''),
            tracks,
            folder_name
        )
        return f"Exported {len(tracks)} tracks to SMB share."
    
    else:
        raise ValueError(f"Unknown storage type: {storage_type}")


def fetch_komoot_tracks(start_date, end_date, complete_only, exercise_type, api_key=None):
    """Fetch tracks from Komoot API with filtering"""
    if not api_key or ':' not in api_key:
        raise ValueError("Komoot API Key in 'email:password' format is required.")

    email, password = api_key.split(':', 1)
    komoot_api = KomootApi()
    komoot_api.login(email, password)

    tracks = []
    page = 0
    has_more = True

    while has_more:
        tours = komoot_api.fetch_tours(page)
        if not tours:
            break

        for tour in tours:
            # Filter by date range
            tour_date = tour.get('date')
            if tour_date:
                if tour_date.endswith('Z'):
                    tour_datetime = datetime.fromisoformat(tour_date[:-1]).replace(tzinfo=timezone.utc)
                else:
                    tour_datetime = datetime.fromisoformat(tour_date)
                tour_datetime_naive = tour_datetime.replace(tzinfo=None)
                if tour_datetime_naive < start_date or tour_datetime_naive > end_date:
                    continue

            # Filter by completion status
            tour_type = tour.get('type')
            if complete_only and tour_type != 'tour_recorded':
                continue

            # Filter by exercise type (sport)
            sport = tour.get('sport')
            if exercise_type and sport != exercise_type:
                continue

            # Fetch detailed tour and generate GPX
            detailed_tour = komoot_api.fetch_detailed_tour(tour['id'])
            gpx_data = komoot_api.generate_gpx(detailed_tour)

            tracks.append({
                'name': tour['name'],
                'gpx_data': gpx_data
            })

        page += 1
        if len(tours) < 30:
            has_more = False

    return tracks


def save_to_s3(endpoint: str, bucket: str, access_key: str, secret_key: str, 
               tracks: List[Dict], folder_name: Optional[str] = None):
    """Save GPX files to S3-compatible storage"""
    if not all([endpoint, bucket, access_key, secret_key]):
        raise ValueError("S3 configuration incomplete: endpoint, bucket, access_key, and secret_key are required")

    s3 = boto3.client('s3',
                      endpoint_url=endpoint,
                      aws_access_key_id=access_key,
                      aws_secret_access_key=secret_key)

    for track in tracks:
        safe_key = sanitize_filename(track['name']) + '.gpx'
        if folder_name:
            safe_key = f"{folder_name.rstrip('/')}/{safe_key}"
        s3.put_object(Bucket=bucket, Key=safe_key, Body=track['gpx_data'].encode('utf-8'))


def save_to_nfs(nfs_path: str, tracks: List[Dict], folder_name: Optional[str] = None):
    """Save GPX files to a local/NFS mounted path"""
    if not nfs_path:
        raise ValueError("NFS path is required")

    # Build the target directory
    target_dir = nfs_path
    if folder_name:
        target_dir = os.path.join(nfs_path, folder_name)

    # Create directory if it doesn't exist
    os.makedirs(target_dir, exist_ok=True)

    for track in tracks:
        safe_name = sanitize_filename(track['name']) + '.gpx'
        file_path = os.path.join(target_dir, safe_name)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(track['gpx_data'])


def save_to_smb(server: str, share: str, username: str, password: str, 
                path: str, tracks: List[Dict], folder_name: Optional[str] = None):
    """Save GPX files to SMB/CIFS share"""
    if not all([server, share, username, password]):
        raise ValueError("SMB configuration incomplete: server, share, username, and password are required")

    if not SMB_AVAILABLE:
        raise ImportError("SMB support requires smbprotocol. Install with: pip install smbprotocol")

    # Build target path
    target_path = path.strip('/\\') if path else ''
    if folder_name:
        target_path = f"{target_path}/{folder_name}" if target_path else folder_name

    # Connect to SMB server
    connection = Connection(uuid=None, server=server, port=445)
    connection.connect()

    try:
        session = Session(connection, username=username, password=password)
        session.connect()

        tree = TreeConnect(session, f"\\\\{server}\\{share}")
        tree.connect()

        try:
            # Create directory if needed
            if target_path:
                _smb_makedirs(tree, target_path)

            # Write each track
            for track in tracks:
                safe_name = sanitize_filename(track['name']) + '.gpx'
                file_path = f"{target_path}/{safe_name}" if target_path else safe_name
                
                _smb_write_file(tree, file_path, track['gpx_data'].encode('utf-8'))

        finally:
            tree.disconnect()
    finally:
        connection.disconnect()


def _smb_makedirs(tree: 'TreeConnect', path: str):
    """Create directories on SMB share (recursive)"""
    parts = path.replace('\\', '/').strip('/').split('/')
    current = ''
    
    for part in parts:
        current = f"{current}/{part}" if current else part
        try:
            dir_open = Open(tree, current)
            dir_open.create(
                ImpersonationLevel.Impersonation,
                FileAttributes.FILE_ATTRIBUTE_DIRECTORY,
                ShareAccess.FILE_SHARE_READ | ShareAccess.FILE_SHARE_WRITE,
                CreateDisposition.FILE_OPEN_IF,
                0x00200021  # FILE_DIRECTORY_FILE | FILE_SYNCHRONOUS_IO_NONALERT
            )
            dir_open.close()
        except Exception:
            pass  # Directory might already exist


def _smb_write_file(tree: 'TreeConnect', path: str, data: bytes):
    """Write a file to SMB share"""
    file_open = Open(tree, path)
    file_open.create(
        ImpersonationLevel.Impersonation,
        FileAttributes.FILE_ATTRIBUTE_NORMAL,
        ShareAccess.FILE_SHARE_READ,
        CreateDisposition.FILE_OVERWRITE_IF,
        0x00000044  # FILE_NON_DIRECTORY_FILE | FILE_SYNCHRONOUS_IO_NONALERT
    )
    try:
        file_open.write(data, 0)
    finally:
        file_open.close()
