"""Conservative component impact and complete local Git diff collection. No secrets/network."""
import json
import os
from pathlib import Path
import re
import subprocess

COMPONENTS = ('android', 'ios', 'backend', 'web')


def classify(paths, complete=True):
    result = {c: {'validation': False, 'release': False, 'reasons': set()} for c in COMPONENTS}
    def mark(components, reason, release=False):
        for c in components:
            result[c]['validation'] = True
            result[c]['release'] |= release
            result[c]['reasons'].add(reason)
    if not complete:
        mark(COMPONENTS, 'incomplete_diff', True)
    for path in paths:
        if path == '.github/workflows/ios-testflight-manual.yml':
            continue  # Scope job still validates YAML/policy; never builds an app for this file alone.
        if path.startswith(('android/', 'ios/', 'website/')):
            c = 'web' if path.startswith('website/') else path.split('/')[0]
            mark([c], 'component_files', True)
        elif path.startswith('supabase/'):
            mark(('android', 'ios'), 'shared_database')
            mark(['backend'], 'shared_database', True)
        elif path.startswith('backend/'):
            mark(['backend'], 'backend_files', True)
            if path.startswith(('backend/contact_', 'backend/tests/test_contact')):
                mark(['web'], 'contact_contract')
            elif path.endswith('.md') or path.startswith('backend/tests/'):
                pass
            else:
                # Shared API/auth/worker code: default to all clients until explicitly classified.
                clients = ('android', 'ios') if path in ('backend/device_api.py', 'backend/take_session_metadata.py') else ('android', 'ios', 'web')
                mark(clients, 'shared_backend_contract')
        elif path in tuple('.github/workflows/' + c + '.yml' for c in COMPONENTS):
            mark([Path(path).stem], 'component_workflow', True)
        elif path in ('.github/android_gradle_retry.py', '.github/test_android_gradle_retry.py',
                      '.github/prepare_robolectric_runtime.py', '.github/test_robolectric_runtime.py',
                      '.github/robolectric_runtime.json', '.github/robolectric-offline.init.gradle'):
            mark(['android'], 'android_validation_tooling')
        elif path.startswith('assets/'):
            mark(('android', 'ios', 'web'), 'shared_assets', True)
        else:
            mark(COMPONENTS, 'unclassified_path', True)
    for state in result.values():
        state['reasons'] = sorted(state['reasons']) or ['unaffected_by_complete_diff']
    return result


def changed_paths(event_name, event, git=None):
    """No API file cap. Both names for renames, deletions included; failures fail conservatively."""
    git = git or (lambda *args: subprocess.check_output(['git', *args]))
    try:
        if event_name == 'pull_request':
            base, head = event['pull_request']['base']['sha'], event['pull_request']['head']['sha']
        elif event_name == 'push':
            base, head = event['before'], event['after']
        else:
            return [], False
        if not all(re.fullmatch(r'[0-9a-f]{40}', s) and s != '0' * 40 for s in (base, head)):
            return [], False
        if event_name == 'pull_request':
            base = git('merge-base', base, head).decode().strip()
        raw = git('diff', '--name-status', '-z', '--find-renames', base, head, '--')
        parts = raw.decode('utf-8', errors='strict').split('\0')
        if parts.pop() != '':
            return [], False
        paths, i = [], 0
        while i < len(parts):
            status = parts[i]; i += 1
            count = 2 if status.startswith(('R', 'C')) else 1
            if not re.fullmatch(r'(?:[AMDUT]|[RC]\d+)', status):
                return [], False
            for _ in range(count):
                path = parts[i]; i += 1
                if not path or path.startswith('/') or '..' in path.split('/'):
                    return [], False
                paths.append(path)
        return paths, True
    except (KeyError, ValueError, IndexError, UnicodeError, subprocess.SubprocessError, OSError):
        return [], False


def main():
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    paths, complete = changed_paths(os.environ['GITHUB_EVENT_NAME'], event)
    result = classify(paths, complete)
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        for c, state in result.items():
            for field in ('validation', 'release'):
                output.write(f'{c}_{field}={str(state[field]).lower()}\n')
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
        summary.write('## Component scope\nComplete diff: ' + str(complete) + '\n\n')
        for c, state in result.items():
            summary.write(f"- {c}: validation={state['validation']}, release={state['release']}; {', '.join(state['reasons'])}\n")


if __name__ == '__main__':
    main()
