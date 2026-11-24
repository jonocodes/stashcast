#!/usr/bin/env python3
"""Decide which Docker images CI builds and how to tag them.

Prints a JSON list of build targets for the GitHub Actions matrix. When run
inside Actions it writes `targets=<json>` to $GITHUB_OUTPUT instead.

Tagging scheme (SemVer, see "Versions and releases" in the README):

  push to main         -> latest, sha-<short>
  push tag vX.Y.Z      -> X.Y.Z, X.Y, plus stable if it is the newest release
  push tag vX.Y.Z-rc.1 -> X.Y.Z-rc.1 only
  manual run           -> rebuild main as latest, and the newest release as
                          X.Y and stable, to pick up new yt-dlp releases and
                          base image fixes. X.Y.Z and sha-* tags never change.
  pull request         -> build and smoke test only, nothing is pushed
"""

import json
import os
import re
import subprocess
import tomllib

SEMVER_TAG = re.compile(r'^v(\d+)\.(\d+)\.(\d+)(-[0-9A-Za-z.-]+)?$')


def target(image, ref, tags, version, branch, push=True):
    return {
        'ref': ref,
        'branch': branch,  # shown on the About page
        'push': push,
        'tags': ','.join(f'{image}:{tag}' for tag in tags),
        'version': version,
    }


def newest_first(release_tags):
    """Final release tags (no pre-releases), newest first."""
    finals = [t for t in release_tags if (m := SEMVER_TAG.match(t)) and not m[4]]
    return sorted(
        finals, key=lambda t: tuple(int(n) for n in SEMVER_TAG.match(t).groups()[:3]), reverse=True
    )


def plan(event, ref, sha, image, release_tags, version_at_tag=None):
    """Return the build targets for one workflow run.

    release_tags: every v* tag in the repo.
    version_at_tag: pyproject.toml version at the pushed tag (tag pushes only).
    """
    releases = newest_first(release_tags)

    if event == 'pull_request':
        return [target(image, sha, ['pr'], f'pr-{sha[:7]}', 'pull-request', push=False)]

    if event == 'push' and ref.startswith('refs/tags/'):
        tag = ref.removeprefix('refs/tags/')
        match = SEMVER_TAG.match(tag)
        if not match:
            raise SystemExit(f'{tag} is not a vX.Y.Z version tag')
        version = tag[1:]
        if version != version_at_tag:
            raise SystemExit(
                f'Tag {tag} does not match the pyproject.toml version ({version_at_tag}). '
                f'Use `just release {version}` to bump and tag together.'
            )
        if match[4]:  # pre-release
            return [target(image, tag, [version], version, tag)]
        tags = [version, f'{match[1]}.{match[2]}']
        if releases and releases[0] == tag:
            tags.append('stable')
        return [target(image, tag, tags, version, tag)]

    if event == 'push' and ref == 'refs/heads/main':
        return [target(image, sha, ['latest', f'sha-{sha[:7]}'], f'main-{sha[:7]}', 'main')]

    if event == 'workflow_dispatch':
        targets = [target(image, 'main', ['latest'], 'main', 'main')]
        if releases:
            newest = releases[0]
            major, minor, _patch, _pre = SEMVER_TAG.match(newest).groups()
            targets.append(
                target(image, newest, [f'{major}.{minor}', 'stable'], newest[1:], newest)
            )
        return targets

    raise SystemExit(f'Nothing to build for event={event} ref={ref}')


def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()


def main():
    event = os.environ['GITHUB_EVENT_NAME']
    ref = os.environ['GITHUB_REF']
    image = f'ghcr.io/{os.environ["GITHUB_REPOSITORY"].lower()}'
    release_tags = git('tag', '--list', 'v*').split()

    version_at_tag = None
    if ref.startswith('refs/tags/'):
        pyproject = git('show', f'{ref}:pyproject.toml')
        version_at_tag = tomllib.loads(pyproject)['project']['version']

    targets = plan(event, ref, os.environ['GITHUB_SHA'], image, release_tags, version_at_tag)

    output = os.environ.get('GITHUB_OUTPUT')
    if output:
        with open(output, 'a') as f:
            f.write(f'targets={json.dumps(targets)}\n')
    print(json.dumps(targets, indent=2))


if __name__ == '__main__':
    main()
