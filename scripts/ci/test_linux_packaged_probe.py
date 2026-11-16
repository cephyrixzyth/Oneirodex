"""Source/archive/fence tests only; no package or desktop execution."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock
import zipfile

spec = importlib.util.find_spec('probe_linux_packaged')
probe = __import__('probe_linux_packaged') if spec else None
SOURCE = 'dc8e0ddea9ef2e4b6ba3ba8a905021c5dc2674f3'
DIGEST = '106d0dd61f7aa59f385fdca74272ff39725fb9f604ef6c23e2be2ab754561270'


def archive(members):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        for name, content, kind in members:
            info = zipfile.ZipInfo(name); info.external_attr = (kind | 0o644) << 16
            z.writestr(info, content)
    return out.getvalue()


class LinuxPackageGuards(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(probe, 'Linux actual-package guards must precede native execution')
        self.run = {'head_sha': SOURCE, 'head_branch': 'codex/release-v1.1.9', 'event': 'push',
                    'status': 'completed', 'conclusion': 'success'}
        self.artifact = {'id': 14197603603, 'name': 'oneirodex-full-linux', 'expired': False,
                         'digest': 'sha256:' + DIGEST, 'size_in_bytes': 85645912}
        self.env = {'GITHUB_ACTIONS': 'true', 'RUNNER_OS': 'Linux',
                    'GITHUB_REPOSITORY': 'cephyrixzyth/Oneirodex', 'GITHUB_RUN_ID': '123'}

    def test_qualified_source_and_each_wrong_source_metadata_are_distinguished(self):
        self.assertEqual(probe.validate_source(self.run, [self.artifact], SOURCE, DIGEST), self.artifact)
        for key, value in [('head_sha', 'a'*40), ('head_branch', 'main'), ('event', 'pull_request'),
                           ('status', 'in_progress'), ('conclusion', 'failure')]:
            with self.subTest(key=key), self.assertRaises(probe.ProbeFailure):
                probe.validate_source({**self.run, key: value}, [self.artifact], SOURCE, DIGEST)

    def test_retired_collection_bug_package_cannot_be_substituted_for_new_source(self):
        old_source='6a03c6fbdadcdc8f585d0012b3a36879e408fa0b'
        old_digest='933c7bdae0ba086fa3bdbf6facad07c512402133fe8cdf2791d515ccb3289994'
        old_artifact={**self.artifact,'id':14097566864,'digest':'sha256:'+old_digest,'size_in_bytes':85649119}
        with self.assertRaises(probe.ProbeFailure):
            probe.validate_source({**self.run,'head_sha':old_source},[old_artifact],old_source,old_digest)

    def test_retired_stale_offline_label_package_cannot_be_substituted_for_new_source(self):
        old_source='ce8c35a6980891ef85c26cb64aa0d8a3ecc9e867'
        old_digest='7e253a922f9481715b399b217821822cb317dff13e83192a0ce0c8e33b4d1749'
        old_artifact={**self.artifact,'id':14173989223,'digest':'sha256:'+old_digest,'size_in_bytes':85645568}
        with self.assertRaises(probe.ProbeFailure):
            probe.validate_source({**self.run,'head_sha':old_source},[old_artifact],old_source,old_digest)

    def test_retired_search_bug_package_cannot_be_substituted_for_new_source(self):
        old_source='effe86ec3045ef8e600c35994ecd3fa2b8eb58b1'
        old_digest='f2f099bbcf6ae4dc8efcf6021042c5f402b2ccb0a5e92bcc00ccc87e33c89dcb'
        old_artifact={**self.artifact,'id':14173537237,'digest':'sha256:'+old_digest,'size_in_bytes':85648068}
        with self.assertRaises(probe.ProbeFailure):
            probe.validate_source({**self.run,'head_sha':old_source},[old_artifact],old_source,old_digest)

    def test_artifact_expiry_digest_size_and_ambiguity_fail_closed(self):
        for key, value in [('expired', True), ('digest', 'sha256:'+'b'*64), ('id', True),
                           ('size_in_bytes', 0), ('size_in_bytes', 128*1024*1024+1)]:
            with self.subTest(key=key,value=value), self.assertRaises(probe.ProbeFailure):
                probe.validate_source(self.run, [{**self.artifact, key: value}], SOURCE, DIGEST)
        for artifacts in ([], [self.artifact, copy.deepcopy(self.artifact)],
                          [{**self.artifact, 'name': 'oneirodex-thin-linux'}]):
            with self.assertRaises(probe.ProbeFailure):
                probe.validate_source(self.run, artifacts, SOURCE, DIGEST)

    def test_execution_fence_requires_real_linux_repo_numeric_run_and_ordinary_uid(self):
        probe.require_ci_execution('linux', self.env, 1001)
        for platform, env, uid in [('win32',self.env,1001),('linux',self.env,0),
                                   ('linux',self.env,-1),('linux',{},1001),
                                   ('linux',{**self.env,'GITHUB_REPOSITORY':'foreign/repo'},1001),
                                   ('linux',{**self.env,'GITHUB_RUN_ID':'abc'},1001)]:
            with self.assertRaises(probe.ProbeFailure):probe.require_ci_execution(platform,env,uid)

    def test_linux_selection_rejects_mixed_modes_release_and_missing_pins(self):
        selected={'LINUX_PACKAGED_SMOKE_ONLY':'true','PACKAGE_SOURCE_RUN':'43803881137',
                  'PACKAGE_SOURCE_COMMIT':SOURCE,'PACKAGE_ARCHIVE_DIGEST':DIGEST}
        probe.validate_selection(selected)
        for key,value in [('PROBE_ONLY','true'),('PROBE_FAMILY','true'),('WINDOWS_PACKAGED_SMOKE_ONLY','true'),
                          ('WINDOWS_USER_FIXTURE_ONLY','true'),('RELEASE_TAG','v1.1.9'),
                          ('PACKAGE_SOURCE_RUN',''),('PACKAGE_SOURCE_COMMIT','a'*40),
                          ('PACKAGE_ARCHIVE_DIGEST','b'*64),('LINUX_PACKAGED_SMOKE_ONLY','false')]:
            with self.subTest(key=key),self.assertRaises(probe.ProbeFailure):
                probe.validate_selection({**selected,key:value})

    def test_workspace_is_fresh_contained_and_cannot_be_root_or_foreign(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); work=probe.create_workspace(base/'owned',base)
            self.assertTrue(work.is_dir())
            for path in (work,base,base.parent/'foreign-target'):
                with self.assertRaises(probe.ProbeFailure):probe.create_workspace(path,base)

    def test_archive_selects_only_pinned_deb_and_accepts_known_separate_appimage(self):
        content=b'fake deb bytes'; digest=hashlib.sha256(content).hexdigest()
        data=archive([('deb/Oneirodex_1.1.9_amd64.deb',content,stat.S_IFREG),
                      ('appimage/Oneirodex_1.1.9_amd64.AppImage',b'other payload',stat.S_IFREG)])
        with tempfile.TemporaryDirectory() as tmp:
            target=probe.extract_deb(data,Path(tmp),digest,len(content))
            self.assertEqual(target.read_bytes(),content)
            with self.assertRaises(probe.ProbeFailure):probe.extract_deb(data,Path(tmp),digest,len(content))

    def test_foreign_extra_traversal_symlink_digest_or_size_rejected_before_publish(self):
        content=b'fake deb bytes'; digest=hashlib.sha256(content).hexdigest()
        valid=('deb/Oneirodex_1.1.9_amd64.deb',content,stat.S_IFREG)
        cases=[([valid,('foreign.deb',b'x',stat.S_IFREG)],digest,len(content)),
               ([('../Oneirodex_1.1.9_amd64.deb',content,stat.S_IFREG)],digest,len(content)),
               ([(valid[0],content,stat.S_IFLNK)],digest,len(content)),
               ([(valid[0],content,stat.S_IFDIR)],digest,len(content)),
               ([valid,valid],digest,len(content)),([valid],'0'*64,len(content)),([valid],digest,99)]
        for members,h,size in cases:
            with tempfile.TemporaryDirectory() as tmp, self.subTest(members=[m[0] for m in members]):
                with self.assertRaises(probe.ProbeFailure):probe.extract_deb(archive(members),Path(tmp),h,size)
                self.assertFalse(list(Path(tmp).iterdir()))

    def test_local_cli_refuses_before_gh_workspace_or_native_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            work=Path(tmp)/'must-not-exist'; out=io.StringIO()
            with mock.patch.dict(probe.os.environ,{},clear=True), \
                 mock.patch.object(probe.subprocess,'run',side_effect=AssertionError('no commands')), \
                 contextlib.redirect_stdout(out):
                status=probe.main(['--execute','--work-dir',str(work),'--source-run','43803881137',
                                   '--source-commit',SOURCE,'--archive-digest',DIGEST])
            self.assertEqual(status,2);self.assertEqual(json.loads(out.getvalue())['status'],'unsupported')
            self.assertFalse(work.exists());self.assertNotIn(str(work),out.getvalue())


if __name__=='__main__':unittest.main()
