"""Retry only unambiguous Maven Central 429 dependency-resolution failures."""
import re
import subprocess
import sys
import time

CENTRAL = r"https://(?:repo\.maven\.apache\.org/maven2|repo1\.maven\.org/maven2)/[^'\s]+"
RATE_LIMIT = re.compile(r"Could not (?:GET|HEAD) '" + CENTRAL + r"'\. Received status code 429 from server: Too Many Requests\s*")
RESOURCE = re.compile(r"Could not get resource '" + CENTRAL + r"'\.\s*")


def eligible(output):
    # Ignore incidental warnings/URLs outside Gradle's actual failure explanation.
    sections = re.findall(r"\* What went wrong:\s*\n(.*?)(?=\n\* |\Z)", output, re.S)
    if not sections:
        return False
    for section in sections:
        entries = [(len(line) - len(line.lstrip()), line.strip()[1:].strip())
                   for line in section.splitlines() if line.strip().startswith('>')]
        causes = [cause for _, cause in entries]
        if not causes or not any(RATE_LIMIT.fullmatch(line) for line in causes):
            return False
        for index, cause in enumerate(causes):
            if RATE_LIMIT.fullmatch(cause) or RESOURCE.fullmatch(cause):
                continue
            if re.fullmatch(r"Failed to transform [^\s]+ \([\w.\-]+:[\w.\-]+:[^\s]+\) to match attributes (?:\{[^\r\n]+\}|\*{3}[^\r\n]+\*{3})\.", cause):
                # Only a nested 429 can justify this envelope, never a sibling error.
                children = []
                for indent, child in entries[index + 1:]:
                    if indent <= entries[index][0]:
                        break
                    children.append(child)
                if children and any(RATE_LIMIT.fullmatch(child) for child in children):
                    continue  # Every child is still checked against the allowlist below.
                return False
            # Gradle's dependency-resolution envelope, never a test/lint/compiler result.
            if re.fullmatch(r"Could not resolve (?:all (?:files|artifacts|dependencies) for configuration .+|[\w.\-]+:[\w.\-]+:[^\s]+)\.?", cause):
                continue
            if re.fullmatch(r"Could not download [^\s]+ \([\w.\-]+:[\w.\-]+:[^\s]+\)", cause):
                continue
            return False
    return True


def run_once(tasks):
    output = []
    with subprocess.Popen(['bash', './gradlew', '--console=plain', *tasks],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding='utf-8', errors='replace') as process:
        for line in process.stdout:
            print(line, end='', flush=True)
            output.append(line)
        return process.wait(), ''.join(output)


def validate(tasks, run=run_once, sleep=time.sleep):
    for attempt in range(1, 4):
        status, output = run(tasks)
        if status == 0 or status < 0 or attempt == 3 or not eligible(output):
            return status if status >= 0 else 128 - status
        delay = 60 * attempt
        print(f'Maven Central HTTP 429: retry {attempt + 1}/3 after {delay} seconds.', flush=True)
        sleep(delay)
    raise AssertionError('unreachable')


if __name__ == '__main__':
    raise SystemExit(validate(sys.argv[1:]))
