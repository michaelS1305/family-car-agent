"""Prepare pinned SDK jars from Maven Central. No cache trust or test-suite retries."""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import ssl
import tempfile
import time
import urllib.error
import urllib.request

MANIFEST = Path(__file__).with_name('robolectric_runtime.json')
BASE = 'https://repo.maven.apache.org/maven2/org/robolectric/android-all-instrumented/'
TRANSIENT = {429, 502, 503, 504}

class PreparationError(Exception):
    pass

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward to an unapproved endpoint or downgrade HTTPS.

def fetch(url):
    return urllib.request.build_opener(NoRedirect()).open(url, timeout=120)

def filename(artifact):
    return 'android-all-instrumented-' + artifact['version'] + '.jar'

def source(artifact):
    return BASE + artifact['version'] + '/' + filename(artifact)

def load_manifest():
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8-sig'))
    for a in manifest['artifacts']:
        if not re.fullmatch(r'[0-9]+-robolectric-[0-9]+-i[0-9]+', a['version']) or not re.fullmatch(r'[0-9a-f]{128}', a['sha512']):
            raise PreparationError('invalid_manifest')
    return manifest

def digest(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha512').hexdigest()

def log(artifact, attempt, status, reason):
    print(f"ROBOLECTRIC_PREP artifact=org.robolectric:android-all-instrumented:{artifact['version']} attempt={attempt} http_status={status} reason={reason}", flush=True)

def prepare(artifact, directory, opener=fetch, sleep=time.sleep):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / filename(artifact)
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_file() or digest(target) != artifact['sha512']:
            log(artifact, 0, 'none', 'existing_integrity_failed')
            raise PreparationError('existing_integrity_failed')
        log(artifact, 0, 'none', 'verified_existing')
        return target
    for attempt in range(1, 4):
        temporary = None
        status = 'none'
        try:
            with opener(source(artifact)) as response:
                status = response.status
                if status != 200:
                    raise urllib.error.HTTPError(source(artifact), status, '', {}, None)
                length = response.headers.get('Content-Length')
                count = 0
                with tempfile.NamedTemporaryFile(dir=directory, prefix='.download-', suffix='.partial', delete=False) as out:
                    temporary = Path(out.name)
                    while chunk := response.read(1024 * 1024):
                        out.write(chunk); count += len(chunk)
                    out.flush(); os.fsync(out.fileno())
                if length is not None and count != int(length):
                    raise PreparationError('partial_download')
                if digest(temporary) != artifact['sha512']:
                    raise PreparationError('checksum_mismatch')
                os.replace(temporary, target)
                temporary = None
                log(artifact, attempt, status, 'verified_download')
                return target
        except urllib.error.HTTPError as exc:
            log(artifact, attempt, exc.code, 'transient_http' if exc.code in TRANSIENT else 'permanent_http')
            if exc.code not in TRANSIENT or attempt == 3:
                raise PreparationError('http_failure') from None
            sleep(60 * attempt)
        except PreparationError as exc:
            log(artifact, attempt, status, str(exc))
            raise
        except (ssl.SSLError, urllib.error.URLError) as exc:
            tls = isinstance(exc, ssl.SSLError) or isinstance(getattr(exc, 'reason', None), ssl.SSLError)
            reason = 'tls_failure' if tls else 'transport_failure'
            log(artifact, attempt, status, reason)
            raise PreparationError(reason) from None
        except http.client.IncompleteRead:
            log(artifact, attempt, status, 'partial_download')
            raise PreparationError('partial_download') from None
        except Exception:
            log(artifact, attempt, status, 'unclassified_failure')
            raise PreparationError('unclassified_failure') from None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    try:
        for artifact in load_manifest()['artifacts']:
            prepare(artifact, args.directory)
    except PreparationError:
        return 1
    except Exception:
        print("ROBOLECTRIC_PREP reason=configuration_or_filesystem_failure", flush=True)
        return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
