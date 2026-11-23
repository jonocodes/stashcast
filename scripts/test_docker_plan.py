"""Tests for the Docker image tagging plan used by .github/workflows/docker.yml."""

import pytest

from docker_plan import plan

IMAGE = 'ghcr.io/jonocodes/stashcast'
SHA = 'abcdef1234567890'


def tags(targets):
    return [t['tags'].split(',') for t in targets]


def test_pull_request_builds_but_does_not_push():
    [t] = plan('pull_request', 'refs/pull/7/merge', SHA, IMAGE, ['v0.1.0'])
    assert t['push'] is False


def test_push_to_main_publishes_latest_and_sha():
    targets = plan('push', 'refs/heads/main', SHA, IMAGE, ['v0.1.0'])
    assert tags(targets) == [[f'{IMAGE}:latest', f'{IMAGE}:sha-abcdef1']]
    assert targets[0]['push'] is True
    assert targets[0]['branch'] == 'main'


def test_release_tag_publishes_version_minor_and_stable():
    targets = plan(
        'push', 'refs/tags/v0.2.0', SHA, IMAGE, ['v0.1.0', 'v0.2.0'], version_at_tag='0.2.0'
    )
    assert targets[0]['ref'] == 'v0.2.0'
    assert tags(targets) == [[f'{IMAGE}:0.2.0', f'{IMAGE}:0.2', f'{IMAGE}:stable']]


def test_patch_for_older_line_does_not_move_stable():
    targets = plan(
        'push',
        'refs/tags/v0.1.1',
        SHA,
        IMAGE,
        ['v0.1.0', 'v0.1.1', 'v0.2.0'],
        version_at_tag='0.1.1',
    )
    assert tags(targets) == [[f'{IMAGE}:0.1.1', f'{IMAGE}:0.1']]


def test_versions_compare_numerically():
    targets = plan(
        'push', 'refs/tags/v0.10.0', SHA, IMAGE, ['v0.9.0', 'v0.10.0'], version_at_tag='0.10.0'
    )
    assert f'{IMAGE}:stable' in tags(targets)[0]


def test_prerelease_only_gets_its_own_tag():
    targets = plan(
        'push',
        'refs/tags/v1.0.0-rc.1',
        SHA,
        IMAGE,
        ['v0.2.0', 'v1.0.0-rc.1'],
        version_at_tag='1.0.0-rc.1',
    )
    assert tags(targets) == [[f'{IMAGE}:1.0.0-rc.1']]


def test_tag_must_match_pyproject_version():
    with pytest.raises(SystemExit, match='does not match'):
        plan('push', 'refs/tags/v0.3.0', SHA, IMAGE, ['v0.3.0'], version_at_tag='0.2.0')


def test_non_semver_tag_is_rejected():
    with pytest.raises(SystemExit, match='not a vX.Y.Z'):
        plan('push', 'refs/tags/v1', SHA, IMAGE, ['v1'], version_at_tag='1')


def test_manual_run_rebuilds_floating_tags_only():
    targets = plan(
        'workflow_dispatch', 'refs/heads/main', SHA, IMAGE, ['v0.1.0', 'v0.2.1', 'v0.3.0-rc.1']
    )
    assert [(t['ref'], t['tags'].split(',')) for t in targets] == [
        ('main', [f'{IMAGE}:latest']),
        ('v0.2.1', [f'{IMAGE}:0.2', f'{IMAGE}:stable']),
    ]


def test_manual_run_without_releases_only_rebuilds_main():
    targets = plan('workflow_dispatch', 'refs/heads/main', SHA, IMAGE, [])
    assert tags(targets) == [[f'{IMAGE}:latest']]
