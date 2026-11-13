//! Account-bound recovery metadata and a single reporter lease per profile/game.
use fs2::FileExt;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::fs::{self, File, OpenOptions};
use std::io;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub(super) struct LaunchRecord {
    pub game_uuid: String,
    pub pid: u32,
    pub launch_id: String,
}
#[derive(Default, Serialize)]
pub(super) struct LaunchInventory {
    pub supported: bool,
    pub launches: Vec<LaunchRecord>,
    pub unverified: usize,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Binding {
    version: u32,
    profile: String,
}

fn validate_profile(profile: &str) -> io::Result<()> {
    if profile.len() == 64
        && profile
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        Ok(())
    } else {
        Err(io::Error::other("Invalid launch profile binding"))
    }
}
fn read_binding(root: &Path) -> io::Result<Binding> {
    let path = root.join("binding.json");
    let metadata = fs::symlink_metadata(&path)?;
    if !metadata.is_file() || metadata.file_type().is_symlink() || metadata.len() > 256 {
        return Err(io::Error::other("Invalid launch binding"));
    }
    let binding: Binding = serde_json::from_slice(&fs::read(path)?)?;
    if binding.version != 1 {
        return Err(io::Error::other("Unsupported launch binding"));
    }
    validate_profile(&binding.profile)?;
    Ok(binding)
}
pub(super) fn bind(root: &Path, profile: Option<&str>) -> io::Result<()> {
    match profile {
        Some(profile) => {
            validate_profile(profile)?;
            super::install_recovery::atomic_write(
                &root.join("binding.json"),
                &serde_json::to_vec(&Binding {
                    version: 1,
                    profile: profile.to_owned(),
                })?,
            )
        }
        None => match fs::remove_file(root.join("binding.json")) {
            Err(error) if error.kind() != io::ErrorKind::NotFound => Err(error),
            _ => Ok(()),
        },
    }
}
fn launch_dirs(base: &Path) -> io::Result<Vec<(String, PathBuf)>> {
    if !base.try_exists()? {
        return Ok(Vec::new());
    }
    let canonical = base.canonicalize()?;
    let mut result = Vec::new();
    for entry in fs::read_dir(base)? {
        let entry = entry?;
        let kind = entry.file_type()?;
        let Some(name) = entry.file_name().to_str().map(str::to_owned) else {
            continue;
        };
        let Ok(id) = uuid::Uuid::parse_str(&name) else {
            continue;
        };
        if id.get_version_num() != 4
            || id.to_string() != name
            || !kind.is_dir()
            || kind.is_symlink()
        {
            continue;
        }
        let path = entry.path();
        if path.canonicalize()?.starts_with(&canonical) {
            result.push((name, path));
        }
    }
    Ok(result)
}
pub(super) fn list(
    base: &Path,
    profile: &str,
    supported: bool,
    resolve: impl Fn(&Path, &str) -> io::Result<Option<LaunchRecord>>,
) -> io::Result<LaunchInventory> {
    validate_profile(profile)?;
    let mut inventory = LaunchInventory {
        supported,
        ..Default::default()
    };
    if !supported {
        return Ok(inventory);
    }
    for (id, root) in launch_dirs(base)? {
        // Do not inspect or disclose another profile's processes. A malformed
        // binding cannot prove an account, so it is never eligible for recovery.
        if !matches!(read_binding(&root), Ok(binding) if binding.profile == profile) {
            continue;
        }
        match resolve(base, &id) {
            Ok(Some(record)) if record.launch_id == id && record.pid > 0 => {
                inventory.launches.push(record)
            }
            Ok(None) => {}
            _ => inventory.unverified += 1,
        }
    }
    Ok(inventory)
}
pub(super) fn forget(base: &Path) -> io::Result<()> {
    let mut failed = false;
    for (_, root) in launch_dirs(base)? {
        if let Err(error) = fs::remove_file(root.join("binding.json")) {
            if error.kind() != io::ErrorKind::NotFound {
                failed = true;
            }
        }
    }
    if failed {
        Err(io::Error::other(
            "Some launch recovery bindings could not be removed",
        ))
    } else {
        Ok(())
    }
}

struct Claim {
    id: String,
    _file: File,
}
#[derive(Default)]
struct ClientClaims {
    client: Option<String>,
    claims: HashMap<String, Claim>,
}
#[derive(Default)]
pub(super) struct TrackingClaims(Mutex<ClientClaims>);
impl TrackingClaims {
    pub(super) fn begin_client(&self) -> io::Result<String> {
        let mut state = self
            .0
            .lock()
            .map_err(|_| io::Error::other("Reporter registry unavailable"))?;
        let client = uuid::Uuid::new_v4().to_string();
        state.claims.clear();
        state.client = Some(client.clone());
        Ok(client)
    }
    pub(super) fn acquire(
        &self,
        base: &Path,
        profile: &str,
        game: &str,
        client: &str,
    ) -> io::Result<Option<String>> {
        validate_profile(profile)?;
        if game.is_empty() || game.len() > 128 {
            return Err(io::Error::other("Invalid tracking game"));
        }
        let mut state = self
            .0
            .lock()
            .map_err(|_| io::Error::other("Reporter registry unavailable"))?;
        if state.client.as_deref() != Some(client) {
            return Err(io::Error::other("Reporter client was replaced"));
        }
        let game_hash = format!("{:x}", Sha256::digest(game.as_bytes()));
        let key = format!("{profile}:{game_hash}");
        if state.claims.contains_key(&key) {
            return Ok(None);
        }
        let dir = base.join("tracking").join(profile);
        #[cfg(unix)]
        {
            use std::os::unix::fs::DirBuilderExt;
            fs::DirBuilder::new()
                .recursive(true)
                .mode(0o700)
                .create(&dir)?;
        }
        #[cfg(not(unix))]
        fs::create_dir_all(&dir)?;
        let mut options = OpenOptions::new();
        options.create(true).read(true).write(true).truncate(false);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let file = options.open(dir.join(format!("{game_hash}.lock")))?;
        match file.try_lock_exclusive() {
            Err(error) if error.raw_os_error() == fs2::lock_contended_error().raw_os_error() => {
                return Ok(None)
            }
            Err(error) => return Err(error),
            Ok(()) => {}
        }
        let id = uuid::Uuid::new_v4().to_string();
        state.claims.insert(
            key,
            Claim {
                id: id.clone(),
                _file: file,
            },
        );
        Ok(Some(id))
    }
    pub(super) fn owns(&self, client: &str, id: &str) -> io::Result<bool> {
        let state = self
            .0
            .lock()
            .map_err(|_| io::Error::other("Reporter registry unavailable"))?;
        Ok(state.client.as_deref() == Some(client)
            && state.claims.values().any(|claim| claim.id == id))
    }
    pub(super) fn release(&self, id: &str) -> io::Result<()> {
        let mut state = self
            .0
            .lock()
            .map_err(|_| io::Error::other("Reporter registry unavailable"))?;
        state.claims.retain(|_, claim| claim.id != id);
        Ok(())
    }
    pub(super) fn release_all(&self) -> io::Result<()> {
        let mut state = self
            .0
            .lock()
            .map_err(|_| io::Error::other("Reporter registry unavailable"))?;
        state.claims.clear();
        state.client = None;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    const A: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    const B: &str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    #[test]
    #[ignore = "Synthetic controller role invoked only by the bounded process test"]
    fn claim_holder_fixture() {
        use std::io::Read;
        let root =
            PathBuf::from(std::env::var_os("ONEIRODEX_CLAIM_FIXTURE").expect("owned fixture only"));
        assert!(root.is_absolute());
        assert_eq!(
            fs::read(root.join("owned-marker")).unwrap(),
            b"R2065 controller fixture"
        );
        let claims = TrackingClaims::default();
        let client = claims.begin_client().unwrap();
        assert!(claims.acquire(&root, A, "game", &client).unwrap().is_some());
        fs::write(root.join("claim-ready"), b"held").unwrap();
        std::io::stdin().read_to_end(&mut Vec::new()).unwrap();
        // Process exit releases the OS lease, without touching launch records.
    }
    struct OwnedClaimProcess(std::process::Child);
    impl Drop for OwnedClaimProcess {
        fn drop(&mut self) {
            self.0.stdin.take();
            let _ = self.0.wait();
        }
    }
    #[test]
    fn real_controller_process_excludes_a_second_reporter_and_releases_on_exit() {
        use std::process::{Command, Stdio};
        use std::time::{Duration, Instant};
        let root = tempfile::tempdir().unwrap();
        fs::write(
            root.path().join("owned-marker"),
            b"R2065 controller fixture",
        )
        .unwrap();
        let mut command = Command::new(std::env::current_exe().unwrap());
        command
            .args([
                "--exact",
                "launch_tracking::tests::claim_holder_fixture",
                "--ignored",
                "--nocapture",
            ])
            .env("ONEIRODEX_CLAIM_FIXTURE", root.path())
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x0800_0000);
        }
        let mut child = OwnedClaimProcess(command.spawn().unwrap());
        let deadline = Instant::now() + Duration::from_secs(5);
        while !root.path().join("claim-ready").exists() {
            assert!(child.0.try_wait().unwrap().is_none());
            assert!(Instant::now() < deadline);
            std::thread::sleep(Duration::from_millis(5));
        }
        let contender = TrackingClaims::default();
        let client = contender.begin_client().unwrap();
        assert!(contender
            .acquire(root.path(), A, "game", &client)
            .unwrap()
            .is_none());
        child.0.stdin.take();
        assert!(child.0.wait().unwrap().success());
        let id = contender
            .acquire(root.path(), A, "game", &client)
            .unwrap()
            .expect("closed process cannot keep reporter ownership");
        assert!(contender.owns(&client, &id).unwrap());
    }
    fn launch(base: &Path, profile: &str) -> (String, LaunchRecord) {
        let id = uuid::Uuid::new_v4().to_string();
        let root = base.join(&id);
        fs::create_dir(&root).unwrap();
        bind(&root, Some(profile)).unwrap();
        (
            id.clone(),
            LaunchRecord {
                game_uuid: "fixture-game".into(),
                pid: 123,
                launch_id: id,
            },
        )
    }
    #[test]
    fn only_matching_profile_and_verified_live_launch_can_resume() {
        let base = tempfile::tempdir().unwrap();
        let (id_a, record_a) = launch(base.path(), A);
        let (_, _) = launch(base.path(), B);
        let resolved = std::cell::RefCell::new(Vec::new());
        let result = list(base.path(), A, true, |_, id| {
            resolved.borrow_mut().push(id.to_owned());
            Ok(Some(record_a.clone()))
        })
        .unwrap();
        assert_eq!(result.launches, vec![record_a]);
        assert_eq!(*resolved.borrow(), vec![id_a]);
        let unknown = list(base.path(), A, true, |_, _| {
            Err(io::Error::other("unverified"))
        })
        .unwrap();
        assert!(unknown.launches.is_empty());
        assert_eq!(unknown.unverified, 1);
    }
    #[test]
    fn forget_removes_binding_without_touching_game_or_guardian_metadata() {
        let base = tempfile::tempdir().unwrap();
        let (id, _) = launch(base.path(), A);
        assert!(
            base.path().join(&id).join("binding.json").exists(),
            "fixture must actually have a binding before Forget"
        );
        fs::write(
            base.path().join(&id).join("phase.json"),
            b"guardian still owns this",
        )
        .unwrap();
        forget(base.path()).unwrap();
        assert!(!base.path().join(&id).join("binding.json").exists());
        assert_eq!(
            fs::read(base.path().join(&id).join("phase.json")).unwrap(),
            b"guardian still owns this"
        );
        let result = list(base.path(), A, true, |_, _| {
            panic!("forgotten identity must not be resolved")
        })
        .unwrap();
        assert!(result.launches.is_empty());
    }
    #[test]
    fn independent_claims_and_stale_release_cannot_steal_a_reporter() {
        let base = tempfile::tempdir().unwrap();
        let first = TrackingClaims::default();
        let second = TrackingClaims::default();
        let first_client = first.begin_client().unwrap();
        let second_client = second.begin_client().unwrap();
        let id = first
            .acquire(base.path(), A, "../arbitrary-game-id", &first_client)
            .unwrap()
            .expect("first reporter owns its lease");
        assert!(second
            .acquire(base.path(), A, "../arbitrary-game-id", &second_client)
            .unwrap()
            .is_none());
        assert!(second
            .acquire(base.path(), B, "../arbitrary-game-id", &second_client)
            .unwrap()
            .is_some());
        assert!(second
            .acquire(base.path(), A, "different-game", &second_client)
            .unwrap()
            .is_some());
        first.release(&id).unwrap();
        let replacement = second
            .acquire(base.path(), A, "../arbitrary-game-id", &second_client)
            .unwrap()
            .unwrap();
        assert_ne!(replacement, id);
        first.release(&id).unwrap();
        assert!(first
            .acquire(base.path(), A, "../arbitrary-game-id", &first_client)
            .unwrap()
            .is_none());
        second.release_all().unwrap();
        assert!(first
            .acquire(base.path(), A, "../arbitrary-game-id", &first_client)
            .unwrap()
            .is_some());
    }
    #[test]
    fn replaced_webview_generation_cannot_acquire_or_release_its_successor() {
        let base = tempfile::tempdir().unwrap();
        let claims = TrackingClaims::default();
        let old_client = claims.begin_client().unwrap();
        let old = claims
            .acquire(base.path(), A, "game", &old_client)
            .unwrap()
            .unwrap();
        let new_client = claims.begin_client().unwrap();
        assert!(!claims.owns(&old_client, &old).unwrap());
        assert!(claims.acquire(base.path(), A, "game", &old_client).is_err());
        let new = claims
            .acquire(base.path(), A, "game", &new_client)
            .unwrap()
            .unwrap();
        claims.release(&old).unwrap();
        assert!(claims.owns(&new_client, &new).unwrap());
    }
}
