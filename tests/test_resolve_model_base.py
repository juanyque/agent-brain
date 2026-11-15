from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tests" / "support" / "resolve_model_base.sh"
ZEROS = "0" * 40
BASH = os.environ.get("RESOLVE_MODEL_BASE_BASH", "bash")


class Repo:
    """Throwaway, hermetic git repository (no global config, no network)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(path.parent),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
        path.mkdir()
        self.git("init", "-q", "-b", "main")
        self.counter = 0

    def git(self, *args: str) -> str:
        result = subprocess.run(
            [
                "git",
                "-c", "user.name=Test",
                "-c", "user.email=test@example.invalid",
                "-c", "commit.gpgsign=false",
                *args,
            ],
            cwd=self.path,
            env=self.env,
            text=True,
            capture_output=True,
            check=True,
        )
        return result.stdout.strip()

    def commit(self, name: str | None = None) -> str:
        self.counter += 1
        file_name = name or f"file{self.counter}.txt"
        (self.path / file_name).write_text(f"{self.counter}\n")
        self.git("add", file_name)
        self.git("commit", "-q", "-m", f"commit {self.counter}")
        return self.git("rev-parse", "HEAD")

    def set_remote_main(self, sha: str, branch: str = "main") -> None:
        self.git("update-ref", f"refs/remotes/origin/{branch}", sha)

    def resolve(self, **env: str) -> subprocess.CompletedProcess[str]:
        run_env = dict(self.env)
        run_env.update(env)
        return subprocess.run(
            [BASH, str(SCRIPT)],
            cwd=self.path,
            env=run_env,
            text=True,
            capture_output=True,
            check=False,
        )


class ResolveModelBaseTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="resolve-model-base-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.repo = Repo(tmp / "repo")

    def assertResolves(
        self, result: subprocess.CompletedProcess[str], expected: str
    ) -> None:
        self.assertEqual(result.returncode, 0, result.stderr)
        # stdout carries the SHA and nothing else.
        self.assertEqual(result.stdout, expected + "\n")

    def assertFails(
        self, result: subprocess.CompletedProcess[str], fragment: str = ""
    ) -> None:
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stdout, "")
        self.assertIn("resolve_model_base:", result.stderr)
        self.assertIn(fragment, result.stderr)

    def assertNoFallback(
        self, result: subprocess.CompletedProcess[str], *forbidden: str
    ) -> None:
        self.assertNotEqual(result.returncode, 0)
        for sha in forbidden:
            self.assertNotIn(sha, result.stdout)

    # pull_request

    def test_pull_request_with_valid_base(self) -> None:
        base = self.repo.commit()
        self.repo.commit()
        result = self.repo.resolve(EVENT_NAME="pull_request", PR_BASE_SHA=base)
        self.assertResolves(result, base)

    def test_pull_request_with_missing_base_object_fails(self) -> None:
        self.repo.commit()
        self.repo.commit()
        missing = "ab" * 20
        # No origin remote: the single fetch attempt fails harmlessly offline.
        result = self.repo.resolve(EVENT_NAME="pull_request", PR_BASE_SHA=missing)
        self.assertFails(result, "could not be fetched")

    def test_pull_request_with_empty_base_fails(self) -> None:
        self.repo.commit()
        result = self.repo.resolve(EVENT_NAME="pull_request", PR_BASE_SHA="")
        self.assertFails(result, "empty")

    def test_pull_request_with_non_commit_object_fails(self) -> None:
        self.repo.commit()
        tree = self.repo.git("rev-parse", "HEAD^{tree}")
        result = self.repo.resolve(EVENT_NAME="pull_request", PR_BASE_SHA=tree)
        self.assertFails(result)

    # push to an existing branch

    def test_push_single_commit(self) -> None:
        before = self.repo.commit()
        self.repo.commit()
        result = self.repo.resolve(EVENT_NAME="push", PUSH_BEFORE_SHA=before)
        self.assertResolves(result, before)

    def test_push_several_commits_range_covers_all(self) -> None:
        before = self.repo.commit()
        pushed = [self.repo.commit(), self.repo.commit(), self.repo.commit()]
        result = self.repo.resolve(EVENT_NAME="push", PUSH_BEFORE_SHA=before)
        self.assertResolves(result, before)
        revs = self.repo.git("rev-list", f"{before}..HEAD").split()
        self.assertEqual(set(revs), set(pushed))

    def test_push_without_before_fails(self) -> None:
        self.repo.commit()
        result = self.repo.resolve(EVENT_NAME="push", PUSH_BEFORE_SHA="")
        self.assertFails(result, "PUSH_BEFORE_SHA")

    def test_force_push_diverged_before_still_resolves(self) -> None:
        # `before` (A) exists but is no longer an ancestor of HEAD. The resolver
        # returns A; consumers diffing `A...HEAD` audit from merge-base(A, HEAD)
        # to HEAD, which is not the exact delta A -> HEAD (and may be empty when
        # the push rewinds).
        common = self.repo.commit()
        self.repo.git("checkout", "-q", "-b", "old")
        before = self.repo.commit()
        self.repo.git("checkout", "-q", "main")
        self.repo.commit()
        self.repo.commit()
        result = self.repo.resolve(EVENT_NAME="push", PUSH_BEFORE_SHA=before)
        self.assertResolves(result, before)
        self.assertEqual(self.repo.git("merge-base", before, "HEAD"), common)

    def test_force_push_missing_before_object_fails(self) -> None:
        self.repo.commit()
        self.repo.commit()
        result = self.repo.resolve(EVENT_NAME="push", PUSH_BEFORE_SHA="cd" * 20)
        self.assertFails(result, "could not be fetched")

    def test_missing_before_is_recovered_from_origin(self) -> None:
        # A bare "origin" holds the commit that the local clone lacks.
        origin = self.repo.path.parent / "origin.git"
        subprocess.run(
            ["git", "init", "-q", "--bare", "-b", "main", str(origin)],
            check=True,
            env=self.repo.env,
        )
        self.repo.commit()
        self.repo.git("remote", "add", "origin", str(origin))
        self.repo.git("checkout", "-q", "-b", "side")
        wanted = self.repo.commit()
        self.repo.git("push", "-q", "origin", "side")
        self.repo.git("checkout", "-q", "main")
        self.repo.git("branch", "-q", "-D", "side")
        self.repo.git("update-ref", "-d", "refs/remotes/origin/side")
        self.repo.git("reflog", "expire", "--expire=now", "--all")
        self.repo.git("gc", "-q", "--prune=now")
        self.assertNotEqual(
            subprocess.run(
                ["git", "cat-file", "-e", f"{wanted}^{{commit}}"],
                cwd=self.repo.path,
                env=self.repo.env,
            ).returncode,
            0,
        )
        self.repo.commit()
        result = self.repo.resolve(EVENT_NAME="push", PUSH_BEFORE_SHA=wanted)
        # The fetched commit branches off the first commit, so merge-base resolves.
        self.assertResolves(result, wanted)

    def test_unrelated_histories_fail(self) -> None:
        self.repo.commit()
        self.repo.git("checkout", "-q", "--orphan", "other")
        self.repo.git("rm", "-q", "-rf", ".")
        unrelated = self.repo.commit("other.txt")
        self.repo.git("checkout", "-q", "main")
        self.repo.commit()
        for env in (
            {"EVENT_NAME": "push", "PUSH_BEFORE_SHA": unrelated},
            {"EVENT_NAME": "pull_request", "PR_BASE_SHA": unrelated},
        ):
            with self.subTest(event=env["EVENT_NAME"]):
                self.assertFails(self.repo.resolve(**env), "no history")

    # push creating a branch

    def test_new_branch_with_several_commits_audits_all(self) -> None:
        fork = self.repo.commit()
        self.repo.set_remote_main(fork)
        self.repo.git("checkout", "-q", "-b", "feature")
        branch_commits = [self.repo.commit(), self.repo.commit(), self.repo.commit()]
        result = self.repo.resolve(
            EVENT_NAME="push", PUSH_BEFORE_SHA=ZEROS, DEFAULT_BRANCH="main"
        )
        self.assertResolves(result, fork)
        revs = self.repo.git("rev-list", f"{fork}..HEAD").split()
        self.assertEqual(set(revs), set(branch_commits))

    def test_new_branch_without_default_branch_ref_fails(self) -> None:
        self.repo.commit()
        result = self.repo.resolve(
            EVENT_NAME="push", PUSH_BEFORE_SHA=ZEROS, DEFAULT_BRANCH="main"
        )
        self.assertFails(result, "refs/remotes/origin/main")

    def test_new_branch_without_default_branch_name_fails(self) -> None:
        self.repo.commit()
        result = self.repo.resolve(EVENT_NAME="push", PUSH_BEFORE_SHA=ZEROS)
        self.assertFails(result, "DEFAULT_BRANCH")

    def test_new_branch_default_ref_unrelated_fails(self) -> None:
        self.repo.commit()
        self.repo.git("checkout", "-q", "--orphan", "other")
        self.repo.git("rm", "-q", "-rf", ".")
        unrelated = self.repo.commit("other.txt")
        self.repo.git("checkout", "-q", "main")
        self.repo.set_remote_main(unrelated)
        result = self.repo.resolve(
            EVENT_NAME="push", PUSH_BEFORE_SHA=ZEROS, DEFAULT_BRANCH="main"
        )
        self.assertFails(result, "no merge-base")

    def test_new_branch_on_root_commit_without_parent(self) -> None:
        root = self.repo.commit()
        self.repo.set_remote_main(root)
        result = self.repo.resolve(
            EVENT_NAME="push", PUSH_BEFORE_SHA=ZEROS, DEFAULT_BRANCH="main"
        )
        self.assertResolves(result, root)

    def test_root_commit_is_not_a_fallback_for_missing_base(self) -> None:
        root = self.repo.commit()
        result = self.repo.resolve(EVENT_NAME="pull_request", PR_BASE_SHA="ef" * 20)
        self.assertFails(result)
        self.assertNoFallback(result, root)

    # merge commit as HEAD

    def test_merge_commit_as_head(self) -> None:
        fork = self.repo.commit()
        self.repo.git("checkout", "-q", "-b", "topic")
        topic = self.repo.commit()
        self.repo.git("checkout", "-q", "main")
        main_tip = self.repo.commit()
        self.repo.git("merge", "-q", "--no-ff", "-m", "merge topic", "topic")
        self.assertEqual(len(self.repo.git("rev-list", "--parents", "-n1", "HEAD").split()), 3)
        for before in (main_tip, topic):
            with self.subTest(before=before):
                result = self.repo.resolve(EVENT_NAME="push", PUSH_BEFORE_SHA=before)
                self.assertResolves(result, before)
        self.repo.set_remote_main(fork)
        result = self.repo.resolve(
            EVENT_NAME="push", PUSH_BEFORE_SHA=ZEROS, DEFAULT_BRANCH="main"
        )
        self.assertResolves(result, fork)

    # unsupported events

    def test_workflow_dispatch_and_unknown_events_fail(self) -> None:
        sha = self.repo.commit()
        self.repo.commit()
        for event in ("workflow_dispatch", "schedule", ""):
            with self.subTest(event=event):
                result = self.repo.resolve(
                    EVENT_NAME=event,
                    PR_BASE_SHA=sha,
                    PUSH_BEFORE_SHA=sha,
                    DEFAULT_BRANCH="main",
                )
                self.assertFails(result, "unsupported event; provide an explicit base")

    # regression: never degrade to HEAD, HEAD~1 or the root commit

    def test_bad_inputs_never_fall_back_to_head_parent_or_root(self) -> None:
        root = self.repo.commit()
        parent = self.repo.commit()
        head = self.repo.commit()
        missing = "12" * 20
        cases = (
            {"EVENT_NAME": "pull_request", "PR_BASE_SHA": missing},
            {"EVENT_NAME": "pull_request", "PR_BASE_SHA": ""},
            {"EVENT_NAME": "push", "PUSH_BEFORE_SHA": missing},
            {"EVENT_NAME": "push", "PUSH_BEFORE_SHA": ""},
            {
                "EVENT_NAME": "push",
                "PUSH_BEFORE_SHA": ZEROS,
                "DEFAULT_BRANCH": "main",
            },
            {"EVENT_NAME": "workflow_dispatch"},
            {"EVENT_NAME": "push", "PUSH_BEFORE_SHA": ZEROS},
        )
        for env in cases:
            with self.subTest(env=env):
                result = self.repo.resolve(**env)
                self.assertNoFallback(result, root, parent, head)
                self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
