from types import SimpleNamespace
import unittest

from core.sandbox.base import detect_sandbox_infrastructure_error
from core.sandbox.resource_runner import _configure_posix_sandbox


class FakeResource:
    RLIMIT_CORE = 1
    RLIMIT_AS = 2
    RLIMIT_CPU = 3
    RLIMIT_FSIZE = 4
    RLIMIT_NOFILE = 5
    RLIMIT_NPROC = 6

    def __init__(self):
        self.calls = []

    def setrlimit(self, limit, value):
        self.calls.append((limit, value))


class FakeOS:
    def __init__(self, uid, environment=None):
        self._uid = uid
        self.environ = environment or {}
        self.groups = None
        self.gid = None
        self.uid = None

    def geteuid(self):
        return self._uid

    def setgroups(self, groups):
        self.groups = groups

    def setgid(self, gid):
        self.gid = gid

    def setuid(self, uid):
        self.uid = uid
        self._uid = uid


class FakePwd:
    def __init__(self, identity=None):
        self.identity = identity

    def getpwnam(self, name):
        if self.identity is None:
            raise KeyError(name)
        return self.identity


def options():
    return SimpleNamespace(
        memory_mb=384,
        cpu_seconds=5,
        file_size_mb=2,
        max_files=32,
        max_processes=8,
    )


class ResourceRunnerTests(unittest.TestCase):
    def test_root_drops_to_dedicated_uid_before_enabling_nproc(self):
        resource = FakeResource()
        operating_system = FakeOS(uid=0)
        identity = SimpleNamespace(pw_uid=10001, pw_gid=10001)

        enabled = _configure_posix_sandbox(
            resource, FakePwd(identity), operating_system, options()
        )

        self.assertTrue(enabled)
        self.assertEqual(operating_system.groups, [])
        self.assertEqual(operating_system.gid, 10001)
        self.assertEqual(operating_system.uid, 10001)
        self.assertIn((resource.RLIMIT_NPROC, (8, 8)), resource.calls)

    def test_root_fails_closed_when_image_has_no_sandbox_user(self):
        resource = FakeResource()

        with self.assertRaisesRegex(RuntimeError, "Rebuild the Docker image"):
            _configure_posix_sandbox(resource, FakePwd(), FakeOS(uid=0), options())

        self.assertTrue(
            all(limit != resource.RLIMIT_NPROC for limit, _ in resource.calls)
        )

    def test_non_root_shared_uid_keeps_limits_but_skips_nproc(self):
        resource = FakeResource()
        identity = SimpleNamespace(pw_uid=10001, pw_gid=10001)

        enabled = _configure_posix_sandbox(
            resource, FakePwd(identity), FakeOS(uid=1000), options()
        )

        self.assertFalse(enabled)
        self.assertTrue(
            all(limit != resource.RLIMIT_NPROC for limit, _ in resource.calls)
        )
        self.assertIn(
            (resource.RLIMIT_AS, (384 * 1024 * 1024,) * 2), resource.calls
        )

    def test_detects_previous_ubuntu_nproc_failure(self):
        log = """
          File "/app/core/sandbox/resource_runner.py", line 53, in main
            os.execvpe(command[0], command, os.environ.copy())
        BlockingIOError: [Errno 11] Resource temporarily unavailable: '/usr/bin/python'
        """

        message = detect_sandbox_infrastructure_error(log)

        self.assertIsNotNone(message)
        self.assertIn("RLIMIT_NPROC", message)

    def test_does_not_classify_normal_generated_test_failure_as_infrastructure(self):
        self.assertIsNone(
            detect_sandbox_infrastructure_error("AssertionError: assert 2 == 3")
        )
