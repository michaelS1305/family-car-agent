#!/usr/bin/env python3
"""Sign a previously Xcode-built FCA Dev .app on an ephemeral macOS GitHub runner.

No credentials or private tool output are printed. Never changes the input .app.
"""
import argparse
import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import plistlib
import secrets
import shutil
import subprocess
import sys
import tempfile

TEAM = 'GT43M39TLK'
SOURCE_BUNDLE = 'com.familycaragent.app.dev'
INSTALLED_BUNDLE = 'XTL-255E706B.com.familycaragent.app.dev'
PROFILE_NAME = 'XTL profile 8FC5U3CDL2'

class SignError(Exception):
    pass

def require(condition, message):
    if not condition:
        raise SignError(message)

def call(label, *args):
    r = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        raise SignError(f'{label} failed (exit {r.returncode}); private output suppressed')
    return r.stdout

def decode_secret(name, dest):
    raw = os.environ.get(name, '')
    require(bool(raw), f'Required secret missing: {name}')
    try:
        data = base64.b64decode(''.join(raw.split()), validate=True)
    except Exception:
        raise SignError(f'Invalid Base64 secret: {name}') from None
    require(bool(data), f'Empty secret: {name}')
    dest.write_bytes(data)
    dest.chmod(0o600)

def identity(keychain, certificates):
    import re
    raw = call('Certificate identity lookup', 'security', 'find-identity', '-v', '-p', 'codesigning', str(keychain)).decode()
    ids = re.findall(r'^\s*\d+\)\s+([0-9A-Fa-f]{40})(?=\s|$)', raw, re.M)
    hashes = {hashlib.sha1(bytes(cert)).hexdigest().upper() for cert in certificates}
    matches = [i.upper() for i in ids if i.upper() in hashes]
    require(len(matches) == 1, 'Expected exactly one signing identity authorized by FCA Dev profile')
    return matches[0]

def app_info(path):
    return plistlib.loads((path / 'Info.plist').read_bytes())

def metadata_snapshot(app):
    folder = app / 'Metadata.appintents'
    require(folder.is_dir(), 'App Intents metadata directory missing')
    files = sorted(p for p in folder.rglob('*') if p.is_file())
    require(files, 'App Intents metadata is empty')
    content = b'\n'.join(p.read_bytes() for p in files)
    for action in (b'FCATakeVehicleIntent', b'FCAReturnVehicleIntent'):
        require(action in content, 'Vehicle App Intent missing from metadata')
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}

def decode_entitlements(app):
    raw = call('Signed entitlements read', 'codesign', '-d', '--entitlements', ':-', str(app))
    return plistlib.loads(raw)

def sign(input_app: Path, evidence: Path):
    require(sys.platform == 'darwin', 'Signing requires macOS')
    require(os.environ.get('GITHUB_REF') == 'refs/heads/develop' and os.environ.get('GITHUB_EVENT_NAME') in ('push', 'workflow_dispatch'), 'Signing requires authorized develop workflow')
    require(input_app.is_dir(), 'Input .app directory not found')
    require(evidence.is_dir(), 'Evidence directory not found')
    info = app_info(input_app)
    require(info.get('CFBundleIdentifier') == SOURCE_BUNDLE, 'Xcode source Bundle ID mismatch')
    require(info.get('FCAEnvironment') == 'development', 'Not FCA Development environment')
    require(not list(input_app.rglob('*.appex')), 'Unexpected app extension: review its signing separately')
    original_metadata = metadata_snapshot(input_app)
    # Preserve Dev app data when updating: the installed app uses the XTL-prefixed identity.
    with tempfile.TemporaryDirectory(prefix='fca-dev-sign-') as folder:
        root = Path(folder)
        keychain = root / 'fca-dev.keychain-db'
        cert_file = root / 'certificate.p12'
        profile_file = root / 'profile.mobileprovision'
        decode_secret('FCA_PROBE_P12_BASE64', cert_file)
        decode_secret('FCA_DEV_PROFILE_BASE64', profile_file)
        password = os.environ.get('FCA_PROBE_P12_PASSWORD', '')
        require(bool(password), 'P12 password missing')
        decoded = call('Provisioning profile decoding', 'security', 'cms', '-D', '-i', str(profile_file))
        profile = plistlib.loads(decoded)
