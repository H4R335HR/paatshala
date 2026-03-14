#!/usr/bin/env python3
"""
Zoom Recording Downloader
Automates downloading cloud recordings from Zoom's internal web API.

Usage:
  1. Either log in with --username and let the script open a browser
  2. Or export cookies and CSRF from an existing Zoom browser session
  3. Run: python3 zoomvshare.py --username "you@example.com" --download

"""

import argparse
import getpass
import json
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime, timedelta
from http.cookiejar import MozillaCookieJar
from pathlib import Path

import requests

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:
    PlaywrightTimeoutError = None
    sync_playwright = None


class ZoomRecordingDownloader:
    BASE_URL = "https://zoom.us"
    HEADERS_COMMON = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest, OWASP CSRFGuard Project",
        "Origin": "https://zoom.us",
        "Referer": "https://zoom.us/recording/",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }
    PAGE_SIZE = 15  # Zoom's default

    def __init__(self, cookies_file: str, csrf_token: str, output_dir: str = "./recordings"):
        self.session = requests.Session()
        self.csrf_token = csrf_token
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.jwt = None
        self.jwt_expiry = 0
        self.org_base_url = None  # e.g., https://ictkerala-org.zoom.us

        # Load cookies from Netscape/Mozilla format file
        self._load_cookies(cookies_file)

        # Set common headers
        self.session.headers.update(self.HEADERS_COMMON)
        self.session.headers["Zoom-Csrftoken"] = csrf_token

    @classmethod
    def from_session_auth(
        cls,
        cookies: list,
        csrf_token: str,
        output_dir: str = "./recordings",
        user_agent: str | None = None,
    ):
        """Create a downloader from browser-derived cookies and a CSRF token."""
        downloader = cls.__new__(cls)
        downloader.session = requests.Session()
        downloader.csrf_token = csrf_token
        downloader.output_dir = Path(output_dir)
        downloader.output_dir.mkdir(parents=True, exist_ok=True)
        downloader.jwt = None
        downloader.jwt_expiry = 0
        downloader.org_base_url = None
        downloader.session.headers.update(cls.HEADERS_COMMON)
        if user_agent:
            downloader.session.headers["User-Agent"] = user_agent
        downloader.session.headers["Zoom-Csrftoken"] = csrf_token

        for cookie in cookies:
            downloader.session.cookies.set(
                cookie["name"],
                cookie["value"],
                domain=cookie.get("domain"),
                path=cookie.get("path", "/"),
            )

        return downloader

    def validate_authenticated_session(self) -> bool:
        """Check whether the current requests session appears logged into Zoom."""
        try:
            resp = self.session.get(
                f"{self.BASE_URL}/recording",
                allow_redirects=True,
                timeout=20,
            )
        except Exception as e:
            print(f"[!] Failed to validate Zoom session: {e}")
            return False

        final_url = resp.url
        print(f"[*] Session validation URL: {final_url}")

        login_markers = [
            "/signin",
            "/login",
            "Sign in to Zoom",
            "Zoom Web Portal",
            "login-form",
        ]
        body_sample = resp.text[:2000]
        is_logged_out = any(marker in final_url or marker in body_sample for marker in login_markers)

        if is_logged_out:
            print("[!] The transferred browser session is not authenticated in requests.")
            return False

        print("[+] Requests session looks authenticated")
        return True

    def _load_cookies(self, cookies_file: str):
        """Load cookies from a Netscape-format cookies.txt file."""
        cj = MozillaCookieJar(cookies_file)
        try:
            cj.load(ignore_discard=True, ignore_expires=True)
            self.session.cookies = cj
            print(f"[+] Loaded cookies from {cookies_file}")
        except Exception as e:
            print(f"[!] Failed to load cookies: {e}")
            print("    Make sure the file is in Netscape/Mozilla cookies.txt format.")
            print("    Use a browser extension like 'Get cookies.txt LOCALLY'")
            sys.exit(1)

    def _get_jwt(self):
        """Obtain a short-lived JWT token via the /nak endpoint."""
        now = time.time()
        if self.jwt and now < self.jwt_expiry - 60:
            return self.jwt

        print("[*] Fetching new JWT token...")
        url = f"{self.BASE_URL}/nws/common/2.0/nak?pms=Recording&pms=RecordingContent"
        resp = self.session.post(url, data="")

        if resp.status_code != 200:
            print(f"[!] JWT fetch failed: HTTP {resp.status_code}")
            print(f"    Response: {resp.text[:200]}")
            sys.exit(1)

        self.jwt = resp.text.strip()

        # JWT is valid for 1 hour, refresh after 50 minutes
        self.jwt_expiry = now + 3000
        self.session.headers["Authorization"] = f"Bearer {self.jwt}"
        print("[+] JWT obtained successfully")
        return self.jwt

    def _ensure_jwt(self):
        """Ensure we have a valid JWT before making API calls."""
        self._get_jwt()

    def get_recording_list(self, date_from: str = "", date_to: str = "",
                           search_value: str = "", page: int = 1) -> dict:
        """
        Fetch a page of recordings from the host-list endpoint.

        Args:
            date_from: Start date in MM/DD/YYYY format (empty for all)
            date_to: End date in MM/DD/YYYY format (defaults to today)
            search_value: Search by topic name
            page: Page number (1-indexed)

        Returns:
            dict with 'recordings' list and 'total_records' count
        """
        self._ensure_jwt()

        if not date_to:
            date_to = datetime.now().strftime("%m/%d/%Y")

        url = f"{self.BASE_URL}/nws/recording/1.0/host-list"
        data = urllib.parse.urlencode({
            "from": date_from,
            "to": date_to,
            "search_value": search_value,
            "transcript_keyword": "",
            "search_type": "mixed",
            "p": page,
            "search_status": 0,
            "assistant_host_id": "",
        })

        resp = self.session.post(url, data=data,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})

        if resp.status_code != 200:
            print(f"[!] host-list failed: HTTP {resp.status_code}")
            return {"recordings": [], "total_records": 0}

        result = resp.json().get("result", {})
        recordings = result.get("recordings", [])
        total = result.get("total_records", 0)

        # Capture the org base URL from first result
        if recordings and not self.org_base_url:
            self.org_base_url = recordings[0].get("baseUrl", "")
            print(f"[+] Organization base URL: {self.org_base_url}")

        return {"recordings": recordings, "total_records": total}

    def get_all_recordings(self, date_from: str = "", date_to: str = "",
                            search_value: str = "") -> list:
        """Fetch ALL recordings across all pages."""
        all_recordings = []
        page = 1

        first_page = self.get_recording_list(date_from, date_to, search_value, page=1)
        total = first_page["total_records"]
        all_recordings.extend(first_page["recordings"])

        total_pages = (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE
        print(f"[+] Total recordings: {total} ({total_pages} pages)")

        for page in range(2, total_pages + 1):
            print(f"[*] Fetching page {page}/{total_pages}...")
            result = self.get_recording_list(date_from, date_to, search_value, page=page)
            all_recordings.extend(result["recordings"])
            time.sleep(0.5)  # Be gentle

        return all_recordings

    def limit_recordings(self, recordings: list, limit: int = 0) -> list:
        """Limit recordings to the newest or oldest N entries.

        Positive values keep the newest N entries.
        Negative values keep the oldest abs(N) entries.
        Zero keeps the full list.
        """
        if limit == 0:
            return recordings

        count = min(abs(limit), len(recordings))
        if count == 0:
            return []

        if limit > 0:
            return recordings[:count]

        return recordings[-count:]

    def get_recording_detail_payload(self, meeting_id: str) -> dict:
        """Fetch the raw recording detail payload for a specific meeting."""
        self._ensure_jwt()

        encoded_id = urllib.parse.quote(meeting_id, safe="")
        url = f"{self.BASE_URL}/nws/recording/1.0/detail?meeting_id={encoded_id}"

        resp = self.session.get(url)

        if resp.status_code != 200:
            print(f"[!] detail failed for {meeting_id}: HTTP {resp.status_code}")
            return {}

        result = resp.json().get("result", {})

        if not self.org_base_url:
            self.org_base_url = result.get("baseUrl", "")

        return result

    def get_recording_detail(self, meeting_id: str) -> list:
        """
        Get individual file details (with playId) for a specific recording.

        Args:
            meeting_id: The base64 meetingId from host-list

        Returns:
            List of file dicts with playId, fileName, iconType, etc.
        """
        result = self.get_recording_detail_payload(meeting_id)
        if not result:
            return []

        files_map = result.get("clipFilesResultMap", {})

        # Flatten all clips into a single list
        all_files = []
        for _clip_time, files in files_map.items():
            all_files.extend(files)

        return all_files

    def get_share_data(self, meeting_id: str) -> dict:
        """Fetch meeting-level share metadata for a recording."""
        self._ensure_jwt()

        encoded_id = urllib.parse.quote(meeting_id, safe="")
        url = f"{self.BASE_URL}/nws/recording/1.0/share-data?meetingId={encoded_id}"

        resp = self.session.get(url)

        if resp.status_code != 200:
            print(f"[!] share-data failed for {meeting_id}: HTTP {resp.status_code}")
            return {}

        result = resp.json().get("result", {})

        if not self.org_base_url:
            self.org_base_url = result.get("baseUrl", "")

        return result

    def apply_share_settings(
        self,
        meeting_id: str,
        allow_viewers_download: bool = False,
        allow_viewer_see_transcript: bool = False,
        allow_viewer_see_chat: bool = False,
        enable_passcode: bool = False,
    ) -> bool:
        """Apply the standard share settings before generating a share link."""
        self._ensure_jwt()

        url = f"{self.BASE_URL}/nws/recording/1.0/save-share-setting"
        data = urllib.parse.urlencode({
            "allowViewersDownload": str(allow_viewers_download).lower(),
            "allowViewerSeeTranscript": str(allow_viewer_see_transcript).lower(),
            "allowViewerSeeChat": str(allow_viewer_see_chat).lower(),
            "enablePasscode": str(enable_passcode).lower(),
            "meetingId": meeting_id,
        })

        resp = self.session.post(
            url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if resp.status_code != 200:
            print(f"[!] save-share-setting failed for {meeting_id}: HTTP {resp.status_code}")
            return False

        payload = resp.json()
        if not payload.get("status", False):
            print(f"[!] save-share-setting was rejected for {meeting_id}: {payload}")
            return False

        return True

    def download_file(self, play_id: str, filename: str, dest_dir: Path) -> bool:
        """
        Download a recording file using the playId.

        Args:
            play_id: The playId from the detail endpoint
            filename: Desired filename for the download
            dest_dir: Directory to save the file

        Returns:
            True if download succeeded
        """
        if not self.org_base_url:
            print("[!] Organization base URL not set. Fetch recordings first.")
            return False

        dest_path = dest_dir / filename
        if dest_path.exists():
            print(f"  [=] Already exists: {filename}")
            return True

        # The download URL uses the org subdomain
        download_url = self.build_download_url(play_id)

        print(f"  [↓] Downloading: {filename}...")
        try:
            resp = self.session.get(download_url, stream=True, allow_redirects=True)

            if resp.status_code != 200:
                print(f"  [!] Download failed: HTTP {resp.status_code}")
                # Try alternate URL pattern
                download_url = f"{self.BASE_URL}/rec/download/{play_id}"
                resp = self.session.get(download_url, stream=True, allow_redirects=True)
                if resp.status_code != 200:
                    print(f"  [!] Alternate URL also failed: HTTP {resp.status_code}")
                    return False

            total_size = int(resp.headers.get("content-length", 0))
            downloaded = 0

            with open(dest_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192 * 16):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            pct = downloaded / total_size * 100
                            mb = downloaded / (1024 * 1024)
                            print(f"\r  [↓] {mb:.1f} MB ({pct:.0f}%)", end="", flush=True)

            print(f"\r  [✓] Saved: {filename} ({downloaded / (1024*1024):.1f} MB)")
            return True

        except Exception as e:
            print(f"  [!] Download error: {e}")
            if dest_path.exists():
                dest_path.unlink()
            return False

    def build_download_url(self, play_id: str) -> str:
        """Build the direct download URL for a recording file."""
        if not self.org_base_url:
            print("[!] Organization base URL not set. Fetch recordings first.")
            return ""
        return f"{self.org_base_url}/rec/download/{play_id}"

    def build_share_url(self, share_id: str) -> str:
        """Build the share URL for a recording file."""
        if not self.org_base_url:
            print("[!] Organization base URL not set. Fetch recordings first.")
            return ""
        return f"{self.org_base_url}/rec/share/{share_id}"

    def get_share_url(self, file_info: dict) -> str:
        """Best-effort extraction of a share URL from a recording file payload."""
        direct_url_keys = [
            "shareUrl",
            "shareURL",
            "shareLink",
            "share_link",
            "recordingShareUrl",
        ]
        for key in direct_url_keys:
            value = file_info.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value

        share_id_keys = [
            "sharePlayId",
            "sharePlayID",
            "shareId",
            "shareID",
            "recordingShareId",
            "recordingShareID",
        ]
        for key in share_id_keys:
            value = file_info.get(key)
            if isinstance(value, str) and value:
                return self.build_share_url(value)

        return ""

    def get_share_url_for_meeting(self, meeting_id: str) -> str:
        """Get the meeting-level share URL from Zoom's share-data endpoint."""
        share_data = self.get_share_data(meeting_id)

        direct_url_keys = [
            "shareUrl",
            "shareURL",
            "shareLink",
            "share_link",
        ]
        for key in direct_url_keys:
            value = share_data.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value

        encrypt_meet_id = share_data.get("encryptMeetId", "")
        if isinstance(encrypt_meet_id, str) and encrypt_meet_id:
            return self.build_share_url(encrypt_meet_id)

        return ""

    def ensure_share_settings(self, meeting_id: str) -> dict:
        """Ensure a meeting uses the standard share settings, then refetch share data."""
        share_data = self.get_share_data(meeting_id)
        if not share_data:
            return {}

        needs_update = any([
            share_data.get("allowViewersDownload") is not False,
            share_data.get("allowViewerSeeTranscript") is not False,
            share_data.get("allowViewerSeeChat") is not False,
            bool(share_data.get("recordMeetRawPassword")),
        ])

        if not needs_update:
            return share_data

        print(f"[*] Applying standard share settings for meeting {meeting_id}...")
        updated = self.apply_share_settings(
            meeting_id=meeting_id,
            allow_viewers_download=False,
            allow_viewer_see_transcript=False,
            allow_viewer_see_chat=False,
            enable_passcode=False,
        )
        if not updated:
            return share_data

        return self.get_share_data(meeting_id)

    def download_meeting_recordings(self, meeting: dict, file_types: list = None):
        """
        Download all files for a single meeting recording.

        Args:
            meeting: A recording dict from host-list
            file_types: List of types to download. Options: video, audio, transcript, chat
                        Default: ['video'] (just the MP4)
        """
        if file_types is None:
            file_types = ["video"]

        meeting_id = meeting["meetingId"]
        topic = meeting.get("topic", "Untitled")
        start_time = meeting.get("meetingStartTimeStr", "Unknown")

        # Sanitize topic for use as folder name
        safe_topic = re.sub(r'[<>:"/\\|?*]', '_', topic).strip()
        safe_date = re.sub(r'[<>:"/\\|?*,]', '_', start_time).strip()

        dest_dir = self.output_dir / f"{safe_topic}" / f"{safe_date}"
        dest_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n[*] Processing: {topic} ({start_time})")

        # Get file details
        files = self.get_recording_detail(meeting_id)
        if not files:
            print("  [!] No files found for this recording")
            return

        for f in files:
            icon_type = f.get("iconType", "")
            play_id = f.get("playId", "")
            original_name = f.get("fileName", "unknown")
            display_name = f.get("displayFileName", "")
            file_size_mb = f.get("fileSizeInMB", "")

            # Filter by requested file types
            should_download = False
            if "video" in file_types and f.get("videoFile"):
                should_download = True
            if "audio" in file_types and f.get("audioFile"):
                should_download = True
            if "transcript" in file_types and (f.get("transcriptFile") or f.get("transcriptWebVttFile")):
                should_download = True
            if "chat" in file_types and f.get("chatFile"):
                should_download = True

            if not should_download:
                continue

            print(f"  [{icon_type}] {display_name} ({file_size_mb})")
            self.download_file(play_id, original_name, dest_dir)
            time.sleep(1)  # Throttle between files

    def list_recordings(self, date_from: str = "", date_to: str = "",
                        search_value: str = "", limit: int = 0) -> list:
        """List all recordings with summary info (no download)."""
        recordings = self.get_all_recordings(date_from, date_to, search_value)
        recordings = self.limit_recordings(recordings, limit)

        print(f"\n{'='*80}")
        print(f"{'#':>3}  {'Date':<24}  {'Duration':<10}  {'Size':<10}  {'Topic'}")
        print(f"{'='*80}")

        for i, rec in enumerate(recordings, 1):
            topic = rec.get("topic", "Untitled")
            date = rec.get("meetingStartTimeStr", "Unknown")
            duration = rec.get("meetingDurationStr", "")
            size = rec.get("fileSizeInMB", "")
            print(f"{i:>3}  {date:<24}  {duration:<10}  {size:<10}  {topic}")

        print(f"{'='*80}")
        print(f"Total: {len(recordings)} recordings")
        return recordings

    def list_links(self, date_from: str = "", date_to: str = "",
                   search_value: str = "", file_types: list = None,
                   check_settings: bool = False, limit: int = 0) -> list:
        """List direct download links for recording files."""
        if file_types is None:
            file_types = ["video"]

        recordings = self.get_all_recordings(date_from, date_to, search_value)
        recordings = self.limit_recordings(recordings, limit)
        total_links = 0
        exported_links = []

        for i, rec in enumerate(recordings, 1):
            topic = rec.get("topic", "Untitled")
            date = rec.get("meetingStartTimeStr", "Unknown")
            meeting_id = rec.get("meetingId", "")
            share_data = self.ensure_share_settings(meeting_id) if check_settings else self.get_share_data(meeting_id)
            encrypt_meet_id = share_data.get("encryptMeetId", "")
            share_url = self.build_share_url(encrypt_meet_id) if encrypt_meet_id else ""
            print(f"\n{'='*80}")
            print(f"[{i}/{len(recordings)}] {topic} ({date})")
            if share_url:
                print(f"Share: {share_url}")
                exported_links.append({
                    "title": f"{topic} ({date})",
                    "topic": topic,
                    "date": date,
                    "description": f"{topic} ({date})",
                    "share_url": share_url,
                    "meeting_id": meeting_id,
                    "meeting_number": rec.get("meetingNumber", ""),
                })

            detail_payload = self.get_recording_detail_payload(meeting_id)
            files_map = detail_payload.get("clipFilesResultMap", {})
            files = []
            for _clip_time, clip_files in files_map.items():
                files.extend(clip_files)
            if not files:
                print("  [!] No files found for this recording")
                continue

            for f in files:
                should_list = False
                if "video" in file_types and f.get("videoFile"):
                    should_list = True
                if "audio" in file_types and f.get("audioFile"):
                    should_list = True
                if "transcript" in file_types and (f.get("transcriptFile") or f.get("transcriptWebVttFile")):
                    should_list = True
                if "chat" in file_types and f.get("chatFile"):
                    should_list = True

                if not should_list:
                    continue

                play_id = f.get("playId", "")
                if not play_id:
                    continue

                filename = f.get("fileName", "unknown")
                display_name = f.get("displayFileName", "")
                icon_type = f.get("iconType", "")
                file_size_mb = f.get("fileSizeInMB", "")
                download_url = self.build_download_url(play_id)
                if not share_url and not download_url:
                    continue

                print(f"  [{icon_type}] {display_name} ({file_size_mb})")
                print(f"  File: {filename}")
                if download_url:
                    print(f"  Download: {download_url}")
                total_links += 1

            time.sleep(0.5)

        print(f"\n{'='*80}")
        print(f"Total links: {total_links}")
        return exported_links

    def download_all(self, date_from: str = "", date_to: str = "",
                     search_value: str = "", file_types: list = None,
                     limit: int = 0):
        """Download all recordings matching the filters."""
        recordings = self.get_all_recordings(date_from, date_to, search_value)
        recordings = self.limit_recordings(recordings, limit)
        total = len(recordings)

        print(f"\n[+] Starting download of {total} recordings...")
        for i, rec in enumerate(recordings, 1):
            print(f"\n{'='*60}")
            print(f"[{i}/{total}]")
            self.download_meeting_recordings(rec, file_types)
            time.sleep(1)

        print(f"\n[+] Done! Files saved to: {self.output_dir}")


# --- Save recording metadata to JSON for Moodle upload stage ---

def save_metadata(recordings: list, output_file: str = "recordings_metadata.json"):
    """Save recording metadata to JSON for the Moodle upload stage."""
    metadata = []
    for rec in recordings:
        metadata.append({
            "meeting_id": rec.get("meetingId"),
            "topic": rec.get("topic"),
            "date": rec.get("meetingStartTimeStr"),
            "duration": rec.get("meetingDurationStr"),
            "size_mb": rec.get("fileSizeInMB"),
            "meeting_number": rec.get("meetingNumber"),
            "recording_count": rec.get("recordingCount"),
            "attendees": [a.get("name") for a in rec.get("attendeeInfos", [])],
        })

    with open(output_file, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"[+] Metadata saved to {output_file}")


def save_links(entries: list, output_file: str):
    """Save generated share links to JSON for downstream scripts."""
    with open(output_file, "w") as f:
        json.dump(entries, f, indent=2)
    print(f"[+] Links saved to {output_file}")


def _extract_csrf_from_page(page) -> str:
    """Best-effort extraction of Zoom's CSRF token from page state."""
    js = """
    () => {
      const candidates = [];
      const metaSelectors = [
        'meta[name="csrf-token"]',
        'meta[name="csrfToken"]',
        'meta[name="zoom-csrftoken"]'
      ];
      for (const selector of metaSelectors) {
        const el = document.querySelector(selector);
        if (el?.content) candidates.push(el.content);
      }

      const cookieMatches = document.cookie.match(/(?:^|; )(?:csrftoken|zm_csrf(?:token)?)=([^;]+)/i);
      if (cookieMatches?.[1]) candidates.push(decodeURIComponent(cookieMatches[1]));

      const stores = [window.localStorage, window.sessionStorage];
      for (const store of stores) {
        if (!store) continue;
        for (let i = 0; i < store.length; i += 1) {
          const key = store.key(i);
          if (!key || !/csrf/i.test(key)) continue;
          const value = store.getItem(key);
          if (!value) continue;
          candidates.push(value);
          try {
            const parsed = JSON.parse(value);
            if (parsed?.csrfToken) candidates.push(parsed.csrfToken);
          } catch (e) {}
        }
      }

      return candidates.filter(Boolean);
    }
    """
    candidates = page.evaluate(js)
    return candidates[0] if candidates else ""


def _extract_login_debug_info(page) -> list[str]:
    """Collect visible login-related messages from the current page."""
    js = """
    () => {
      const selectors = [
        '[role="alert"]',
        '[aria-live="assertive"]',
        '[aria-live="polite"]',
        '.alert',
        '.error',
        '.error-msg',
        '.zm-alert__content',
        '.signin-error',
        '.form-item-message',
        '.warning-message',
      ];
      const messages = [];
      for (const selector of selectors) {
        for (const el of document.querySelectorAll(selector)) {
          const text = (el.innerText || el.textContent || '').trim();
          if (text) messages.push(text);
        }
      }
      return [...new Set(messages)];
    }
    """
    try:
        return page.evaluate(js)
    except Exception:
        return []


def _extract_visible_login_controls(page) -> list[str]:
    """Collect visible button/link text on the current page for auth debugging."""
    js = """
    () => {
      const selectors = ['button', '[role="button"]', 'input[type="submit"]', 'a[role="button"]'];
      const controls = [];
      for (const selector of selectors) {
        for (const el of document.querySelectorAll(selector)) {
          const style = window.getComputedStyle(el);
          const visible = style.display !== 'none' && style.visibility !== 'hidden' &&
            (el.offsetWidth > 0 || el.offsetHeight > 0);
          if (!visible) continue;
          const text = (el.innerText || el.textContent || el.value || '').trim();
          if (text) controls.push(`${selector}: ${text}`);
        }
      }
      return [...new Set(controls)].slice(0, 20);
    }
    """
    try:
        return page.evaluate(js)
    except Exception:
        return []


def _extract_login_field_state(page) -> list[str]:
    """Describe visible login-like inputs for debugging selector mismatches."""
    js = """
    () => {
      const inputs = [];
      for (const el of document.querySelectorAll('input')) {
        const style = window.getComputedStyle(el);
        const visible = style.display !== 'none' && style.visibility !== 'hidden' &&
          (el.offsetWidth > 0 || el.offsetHeight > 0);
        if (!visible) continue;
        const type = el.getAttribute('type') || 'text';
        const name = el.getAttribute('name') || '';
        const autocomplete = el.getAttribute('autocomplete') || '';
        const id = el.id || '';
        const valueLength = (el.value || '').length;
        inputs.push(
          `type=${type} name=${name} id=${id} autocomplete=${autocomplete} value_length=${valueLength}`
        );
      }
      return inputs.slice(0, 20);
    }
    """
    try:
        return page.evaluate(js)
    except Exception:
        return []


def _save_login_debug_artifacts(page) -> tuple[str | None, str | None]:
    """Persist screenshot and HTML snapshot for failed login inspection."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = Path(f"zoom_login_debug_{timestamp}.png")
    html_path = Path(f"zoom_login_debug_{timestamp}.html")

    try:
        page.screenshot(path=str(screenshot_path), full_page=True)
    except Exception:
        screenshot_path = None

    try:
        html_path.write_text(page.content(), encoding="utf-8")
    except Exception:
        html_path = None

    return (
        str(screenshot_path) if screenshot_path else None,
        str(html_path) if html_path else None,
    )


def browser_login(
    username: str,
    password: str | None,
    headless: bool = False,
    manual_login: bool = False,
) -> tuple[list, str, str]:
    """
    Log into Zoom in a real browser, then extract authenticated cookies and CSRF.

    This remains best-effort because Zoom may require MFA, CAPTCHA, or SSO.
    The browser stays visible by default so the user can finish those steps.
    """
    if sync_playwright is None:
        print("[!] Playwright is not installed.")
        print("    Install dependencies with: pip install -r requirements.txt")
        print("    Then install browser support with: python -m playwright install chromium firefox")
        sys.exit(1)

    captured_headers = {}

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=headless)
            print("[*] Using Chromium for browser login")
        except Exception as chromium_error:
            print(f"[*] Chromium launch failed, falling back to Firefox: {chromium_error}")
            browser = playwright.firefox.launch(
                executable_path="/usr/bin/firefox",
                headless=headless,
            )
            print("[*] Using Firefox fallback for browser login")
        context = browser.new_context()
        page = context.new_page()

        def capture_request(request):
            token = request.headers.get("zoom-csrftoken")
            if token:
                captured_headers["Zoom-Csrftoken"] = token

        page.on("request", capture_request)

        print("[*] Opening Zoom sign-in page...")
        page.goto("https://zoom.us/signin", wait_until="domcontentloaded")

        email_selectors = [
            'input[type="email"]',
            'input[name="account"]',
            'input[name="email"]',
            'input[name="username"]',
            'input[autocomplete="username"]',
            '#email',
        ]
        password_selectors = [
            'input[type="password"]',
            'input[name="password"]',
            'input[autocomplete="current-password"]',
            '#password',
        ]
        continue_selectors = [
            'button[type="submit"]',
            'input[type="submit"]',
            '[role="button"]',
            'button',
            'a[role="button"]',
        ]

        def find_first_visible(selectors, timeout_ms=0):
            if timeout_ms:
                end_time = time.time() + (timeout_ms / 1000)
                while time.time() < end_time:
                    locator = find_first_visible(selectors, timeout_ms=0)
                    if locator is not None:
                        return locator
                    page.wait_for_timeout(250)
                return None

            for selector in selectors:
                locator = page.locator(selector).first
                try:
                    if locator.count() and locator.is_visible():
                        return locator
                except Exception:
                    continue
            return None

        def click_continue():
            button = find_first_visible(continue_selectors, timeout_ms=2000)
            if button is not None:
                button.click()
                return True
            return False

        def type_like_user(locator, value: str, field_name: str):
            locator.click()
            locator.press("Control+A")
            locator.press("Backspace")
            locator.type(value, delay=75)
            page.wait_for_timeout(250)

            try:
                current_value = locator.input_value()
            except Exception:
                current_value = ""

            if current_value != value:
                try:
                    locator.fill(value)
                    page.wait_for_timeout(150)
                    current_value = locator.input_value()
                except Exception:
                    current_value = ""

            if current_value != value:
                try:
                    locator.evaluate(
                        """(el, newValue) => {
                            el.focus();
                            el.value = newValue;
                            el.dispatchEvent(new Event('input', { bubbles: true }));
                            el.dispatchEvent(new Event('change', { bubbles: true }));
                            el.blur();
                        }""",
                        value,
                    )
                    page.wait_for_timeout(150)
                    current_value = locator.input_value()
                except Exception:
                    current_value = ""

            print(f"[*] {field_name} field value length after fill: {len(current_value)}")
            return current_value == value

        def click_like_user(locator, label: str):
            try:
                locator.scroll_into_view_if_needed(timeout=1000)
            except Exception:
                pass

            box = None
            try:
                box = locator.bounding_box()
            except Exception:
                box = None

            if box:
                x = box["x"] + box["width"] / 2
                y = box["y"] + box["height"] / 2
                page.mouse.move(x - 8, y - 4, steps=8)
                page.wait_for_timeout(120)
                page.mouse.move(x, y, steps=6)
                page.wait_for_timeout(120)
                page.mouse.down()
                page.wait_for_timeout(140)
                page.mouse.up()
            else:
                locator.click(timeout=2000)

            print(f"[*] Clicking auth control: {label}")

        def click_action(labels, timeout_ms=5000):
            end_time = time.time() + (timeout_ms / 1000)
            while time.time() < end_time:
                for selector in continue_selectors:
                    candidates = page.locator(selector)
                    try:
                        count = min(candidates.count(), 10)
                    except Exception:
                        count = 0

                    for index in range(count):
                        candidate = candidates.nth(index)
                        try:
                            if not candidate.is_visible() or not candidate.is_enabled():
                                continue
                            text = (candidate.inner_text(timeout=500) or "").strip().lower()
                        except Exception:
                            text = ""

                        if any(label in text for label in labels):
                            try:
                                candidate.hover(timeout=1000)
                            except Exception:
                                pass
                            page.wait_for_timeout(200)
                            click_like_user(candidate, text or selector)
                            page.wait_for_timeout(350)
                            return True
                page.wait_for_timeout(250)
            return False

        def wait_for_password_screen(timeout_ms=15000):
            password_field = find_first_visible(password_selectors, timeout_ms=timeout_ms)
            if password_field is not None:
                return password_field
            return None

        def submit_current_form():
            js = """
            () => {
              const active = document.activeElement;
              const form = active?.form || document.querySelector('form');
              if (form) {
                if (typeof form.requestSubmit === 'function') {
                  form.requestSubmit();
                } else {
                  form.submit();
                }
                return true;
              }
              return false;
            }
            """
            try:
                return bool(page.evaluate(js))
            except Exception:
                return False

        email_field = find_first_visible(email_selectors, timeout_ms=15000)
        if email_field is None:
            print("[!] Could not find the Zoom email/username field.")
            browser.close()
            sys.exit(1)

        if not type_like_user(email_field, username, "Email"):
            print("[!] Failed to populate the Zoom email field.")
            browser.close()
            sys.exit(1)

        if manual_login:
            print("[*] Manual login mode enabled.")
            print("    Username has been filled in the browser.")
            if password:
                if click_action(["continue", "next", "sign in", "login", "log in"]):
                    page.wait_for_timeout(1000)
                else:
                    email_field.press("Enter")
                    page.wait_for_timeout(1000)

                password_field = wait_for_password_screen(timeout_ms=15000)
                if password_field is not None:
                    type_like_user(password_field, password, "Password")
                    print("    Password has also been filled in the browser.")
                else:
                    print("    Could not auto-fill the password field on the current screen.")
            print("    Complete the Zoom login in the browser window, then press Enter here.")
            input()
        else:
            # Prefer Enter to advance past the email screen — more reliable than text matching
            try:
                email_field.press("Enter")
                page.wait_for_timeout(1000)
            except Exception:
                pass

            # If still on the email screen, fall back to clicking the Continue/Next button
            if find_first_visible(email_selectors) is not None:
                if click_action(["continue", "next"]):
                    page.wait_for_timeout(1000)

            password_field = wait_for_password_screen(timeout_ms=15000)
            if password_field is None:
                print("[!] Could not find the Zoom password field.")
                print("    The sign-in page may require SSO or a different login flow.")
                browser.close()
                sys.exit(1)

            if not type_like_user(password_field, password or "", "Password"):
                print("[!] Failed to populate the Zoom password field.")
                browser.close()
                sys.exit(1)

            # Tab out of the password field so React/Angular re-enables the submit button
            try:
                password_field.press("Tab")
                page.wait_for_timeout(300)
            except Exception:
                pass

            # Try Enter first — most reliable way to submit a login form
            try:
                password_field.press("Enter")
                page.wait_for_timeout(1500)
            except Exception:
                pass

            # If still on sign-in page, try clicking the submit button by type
            if "/signin" in page.url or "/login" in page.url:
                try:
                    page.locator('button[type="submit"]').first.click(timeout=3000)
                    page.wait_for_timeout(1000)
                except Exception:
                    pass

            # If still on sign-in page, try matching the button by visible text
            if "/signin" in page.url or "/login" in page.url:
                if not click_action(["sign in", "login", "log in", "continue", "next"]):
                    if submit_current_form():
                        page.wait_for_timeout(1500)

        print("[*] Waiting for authentication to complete...")
        print("    If Zoom asks for MFA, CAPTCHA, or SSO approval, finish it in the browser window.")
        print("    The script will continue once the recording page is reachable.")

        try:
            page.wait_for_url(re.compile(r"https://(.+\.)?zoom\.us/.*"), timeout=15000)
        except PlaywrightTimeoutError:
            pass

        page.goto("https://zoom.us/recording", wait_until="networkidle")

        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except PlaywrightTimeoutError:
            pass

        current_url = page.url
        page_title = page.title()
        user_agent = page.evaluate("() => navigator.userAgent")
        csrf_token = captured_headers.get("Zoom-Csrftoken") or _extract_csrf_from_page(page)
        cookies = context.cookies(["https://zoom.us", current_url])
        cookie_names = sorted({cookie["name"] for cookie in cookies})
        print(f"[*] Browser landed on: {current_url}")
        print(f"[*] Browser page title: {page_title}")
        print(f"[*] Captured cookies: {', '.join(cookie_names[:12])}")

        if "/signin" in current_url or "/login" in current_url:
            debug_messages = _extract_login_debug_info(page)
            visible_controls = _extract_visible_login_controls(page)
            visible_fields = _extract_login_field_state(page)
            screenshot_path, html_path = _save_login_debug_artifacts(page)
            if debug_messages:
                print("[!] Zoom sign-in page reported:")
                for message in debug_messages[:5]:
                    print(f"    {message}")
            if visible_controls:
                print("[!] Visible login controls:")
                for control in visible_controls[:10]:
                    print(f"    {control}")
            if visible_fields:
                print("[!] Visible input state:")
                for field in visible_fields[:10]:
                    print(f"    {field}")
            if screenshot_path:
                print(f"[!] Saved screenshot: {screenshot_path}")
            if html_path:
                print(f"[!] Saved page HTML: {html_path}")
            print("[!] Browser is still on a Zoom sign-in page. Authentication did not complete.")
            browser.close()
            sys.exit(1)

        if not cookies:
            print("[!] Browser login did not yield any authenticated cookies.")
            browser.close()
            sys.exit(1)

        if not csrf_token:
            print("[!] Browser login succeeded, but CSRF token extraction failed.")
            print("    Use the existing --cookies/--csrf mode if Zoom changed their page behavior.")
            browser.close()
            sys.exit(1)

        print("[+] Browser authentication completed")
        browser.close()
        return cookies, csrf_token, user_agent


def build_downloader(args):
    if args.username:
        password = args.password or getpass.getpass("Zoom password: ")
        cookies, csrf_token, user_agent = browser_login(
            username=args.username,
            password=password,
            headless=args.headless,
            manual_login=args.manual_login,
        )
        downloader = ZoomRecordingDownloader.from_session_auth(
            cookies=cookies,
            csrf_token=csrf_token,
            output_dir=args.output,
            user_agent=user_agent,
        )
        if not downloader.validate_authenticated_session():
            print("[!] Auth handoff failed after browser login.")
            print("    The browser may still need MFA/SSO approval, or Zoom changed its session cookies.")
            sys.exit(1)
        return downloader

    return ZoomRecordingDownloader(
        cookies_file=args.cookies,
        csrf_token=args.csrf,
        output_dir=args.output,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Zoom Recording Downloader - Automate cloud recording downloads",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all recordings using exported browser auth
  python3 zoomvshare.py --cookies cookies.txt --csrf "TOKEN" --list

  # Download all video recordings using exported browser auth
  python3 zoomvshare.py --cookies cookies.txt --csrf "TOKEN" --download

  # Print direct download links for all video recordings
  python3 zoomvshare.py --cookies cookies.txt --csrf "TOKEN" --links

  # Print share links and verify/apply standard share settings first
  python3 zoomvshare.py --cookies cookies.txt --csrf "TOKEN" --links --check-settings

  # Only process the 3 newest matching meetings
  python3 zoomvshare.py --links --search "CSA SGOU" --limit 3

  # Only process the 3 oldest matching meetings
  python3 zoomvshare.py --links --search "CSA SGOU" --limit -3

  # Save generated share links to JSON for Moodle upload
  python3 zoomvshare.py --links --search "CSA SGOU" --links-output zoom_links.json

  # Download recordings after logging in with Zoom credentials
  python3 zoomvshare.py --username "user@example.com" --download

  # Download recordings for a specific batch
  python3 zoomvshare.py --cookies cookies.txt --csrf "TOKEN" --download --search "CSA SGOU"

  # Download with date range (MM/DD/YYYY format)
  python3 zoomvshare.py --cookies cookies.txt --csrf "TOKEN" --download --from-date "02/01/2026" --to-date "03/10/2026"

  # Download video + transcript + chat
  python3 zoomvshare.py --cookies cookies.txt --csrf "TOKEN" --download --types video transcript chat

  # Save metadata JSON (for Moodle upload stage)
  python3 zoomvshare.py --cookies cookies.txt --csrf "TOKEN" --metadata
        """
    )

    auth = parser.add_argument_group("authentication")
    auth.add_argument("--cookies",
                        help="Path to Netscape-format cookies.txt file")
    auth.add_argument("--csrf",
                        help="Zoom-Csrftoken value from browser")
    auth.add_argument("--username",
                      help="Zoom username/email for browser-assisted login")
    auth.add_argument("--password",
                      help="Zoom password for browser-assisted login; omit to prompt securely")
    auth.add_argument("--headless", action="store_true",
                      help="Run browser login headlessly (less reliable if MFA/CAPTCHA is involved)")
    auth.add_argument("--manual-login", action="store_true",
                      help="Open Zoom sign-in and wait for you to complete login manually in the browser")
    parser.add_argument("--output", default="./recordings",
                        help="Output directory (default: ./recordings)")

    # Actions
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--list", action="store_true",
                        help="List all recordings (no download)")
    action.add_argument("--links", action="store_true",
                        help="Print direct download links without downloading files")
    action.add_argument("--download", action="store_true",
                        help="Download recordings")
    action.add_argument("--metadata", action="store_true",
                        help="Save recording metadata as JSON")

    # Filters
    parser.add_argument("--from-date", default="",
                        help="Start date filter (MM/DD/YYYY)")
    parser.add_argument("--to-date", default="",
                        help="End date filter (MM/DD/YYYY)")
    parser.add_argument("--search", default="",
                        help="Search recordings by topic name")

    # Download options
    parser.add_argument("--types", nargs="+", default=["video"],
                        choices=["video", "audio", "transcript", "chat"],
                        help="File types to download (default: video)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Limit to N meetings. Positive keeps the newest N; negative keeps the oldest abs(N); 0 keeps all")
    parser.add_argument("--links-output",
                        help="When used with --links, save the generated share links to a JSON file")
    parser.add_argument("--check-settings", action="store_true",
                        help="When used with --links, verify and apply the standard share settings before generating share URLs")

    args = parser.parse_args()

    using_browser_login = bool(args.username)
    using_manual_auth = bool(args.cookies and args.csrf)

    if not using_browser_login and not using_manual_auth:
        parser.error("provide either --username or both --cookies and --csrf")

    if using_browser_login and (args.cookies or args.csrf):
        parser.error("use either browser login (--username/--password) or manual auth (--cookies/--csrf), not both")

    downloader = build_downloader(args)

    if args.list:
        downloader.list_recordings(
            date_from=args.from_date,
            date_to=args.to_date,
            search_value=args.search,
            limit=args.limit,
        )

    elif args.links:
        links = downloader.list_links(
            date_from=args.from_date,
            date_to=args.to_date,
            search_value=args.search,
            file_types=args.types,
            check_settings=args.check_settings,
            limit=args.limit,
        )
        if args.links_output:
            save_links(links, args.links_output)

    elif args.download:
        downloader.download_all(
            date_from=args.from_date,
            date_to=args.to_date,
            search_value=args.search,
            file_types=args.types,
            limit=args.limit,
        )

    elif args.metadata:
        recordings = downloader.get_all_recordings(
            date_from=args.from_date,
            date_to=args.to_date,
            search_value=args.search,
        )
        recordings = downloader.limit_recordings(recordings, args.limit)
        save_metadata(recordings)


if __name__ == "__main__":
    main()
