//! A separate process owns a launch family; closing the UI must not kill games.
#![cfg(any(windows, target_os = "linux"))]
use fs2::FileExt;
use serde::{Deserialize, Serialize};
use std::fs::{self, File, OpenOptions};
use std::io;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

const MODE: &str = "--oneirodex-launch-supervisor";
#[cfg(target_os = "linux")]
mod linux;
#[cfg(windows)]
mod windows;
#[cfg(target_os = "linux")]
use linux::Family;
#[cfg(windows)]
use windows::Family;

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    version: u32,
    launch_id: String,
    game_uuid: String,
    install_root: PathBuf,
    executable: PathBuf,
    #[cfg(test)]
    game_args: Vec<String>,
}

#[derive(Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "phase", rename_all = "snake_case", deny_unknown_fields)]
enum Phase {
    Prepared,
    Started { pid: u32 },
    Finished { pid: u32 },
    Failed,
}

#[cfg(any(windows, target_os = "linux"))]
pub(super) struct Launch {
    pub child: Child,
    pub pid: u32,
    pub launch_id: String,
}

pub(super) fn status(base: &Path, pid: u32, launch_id: Option<&str>) -> io::Result<bool> {
    let Some(id) = launch_id.and_then(|value| uuid::Uuid::parse_str(value).ok()) else {
        return Ok(false);
    };
    if pid == 0 || id.get_version_num() != 4 || Some(id.to_string().as_str()) != launch_id {
        return Ok(false);
    }
    let root = base.join(id.to_string());
    match fs::symlink_metadata(&root) {
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(false),
        Err(error) => return Err(error),
        Ok(_) => {}
    }
    let _request = read_request(&root)?;
    match read_phase(&root)? {
        Phase::Finished { .. } | Phase::Failed | Phase::Prepared => return Ok(false),
        Phase::Started { pid: recorded_pid } if recorded_pid != pid => return Ok(false),
        Phase::Started { .. } => {}
    }
    let lease_path = root.join("alive.lock");
    let metadata = fs::symlink_metadata(&lease_path)?;
    if !metadata.is_file() || metadata.file_type().is_symlink() {
        return Err(io::Error::other("Invalid launch lease"));
    }
    let lease = File::open(lease_path)?;
    match lease.try_lock_exclusive() {
        Err(error) if error.raw_os_error() == fs2::lock_contended_error().raw_os_error() => {
            Ok(true)
        }
        Err(error) => Err(error),
        Ok(()) => {
            // The guardian may have completed between our phase read and lock.
            if matches!(read_phase(&root)?, Phase::Finished { .. } | Phase::Failed) {
                Ok(false)
            } else {
                Err(io::Error::other(
                    "Launch tracking is unavailable; running game state is unverified",
                ))
            }
        }
    }
}

#[cfg(any(windows, target_os = "linux", test))]
fn write_phase(root: &Path, phase: &Phase) -> io::Result<()> {
    super::install_recovery::atomic_write(&root.join("phase.json"), &serde_json::to_vec(phase)?)
}

#[cfg(any(windows, target_os = "linux", test))]
fn read_phase(root: &Path) -> io::Result<Phase> {
    let path = root.join("phase.json");
    let metadata = fs::symlink_metadata(&path)?;
    if !metadata.is_file() || metadata.file_type().is_symlink() || metadata.len() > 1024 {
        return Err(io::Error::other("Invalid launch phase"));
    }
    serde_json::from_slice(&fs::read(path)?).map_err(io::Error::other)
}

fn read_request(root: &Path) -> io::Result<Request> {
    if !root.is_absolute() || fs::symlink_metadata(root)?.file_type().is_symlink() {
        return Err(io::Error::other("Invalid launch directory"));
    }
    let path = root.join("request.json");
    let metadata = fs::symlink_metadata(&path)?;
    if !metadata.is_file() || metadata.file_type().is_symlink() || metadata.len() > 16_384 {
        return Err(io::Error::other("Invalid launch descriptor"));
    }
    let request: Request = serde_json::from_slice(&fs::read(path)?)?;
    let id = uuid::Uuid::parse_str(&request.launch_id).map_err(io::Error::other)?;
    if request.version != 1
        || id.get_version_num() != 4
        || id.to_string() != request.launch_id
        || root.file_name().and_then(|name| name.to_str()) != Some(request.launch_id.as_str())
        || request.game_uuid.is_empty()
        || request.game_uuid.len() > 128
        || !request.install_root.is_absolute()
        || !request.executable.is_absolute()
    {
        return Err(io::Error::other("Invalid launch descriptor"));
    }
    Ok(request)
}

fn validate_executable(request: &Request) -> io::Result<()> {
    super::ensure_path_under_root(&request.executable, &request.install_root)
        .map_err(|_| io::Error::other("Executable is outside the install root"))
}

#[cfg(any(windows, target_os = "linux"))]
fn supervise(root: &Path) -> io::Result<()> {
    let request = read_request(root)?;
    validate_executable(&request)?;
    let mut options = OpenOptions::new();
    options.create_new(true).write(true).read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    // Rust opens a non-inheritable handle / CLOEXEC descriptor. Only this
    // guardian holds the lease; no stale file/PID implies a living launch.
    let lease = options.open(root.join("alive.lock"))?;
    lease.lock_exclusive()?;
    let family = match Family::new() {
        Ok(family) => family,
        Err(error) => {
            let _ = write_phase(root, &Phase::Failed);
            return Err(error);
        }
    };
    write_phase(root, &Phase::Prepared)?;
    let deadline = Instant::now() + Duration::from_secs(10);
    while fs::read(root.join("start")).ok().as_deref() != Some(request.launch_id.as_bytes()) {
        if Instant::now() >= deadline {
            return Err(io::Error::other("Launch was not authorized"));
        }
        thread::sleep(Duration::from_millis(10));
    }
    let mut command = Command::new(&request.executable);
    command
        .current_dir(
            request
                .executable
                .parent()
                .ok_or_else(|| io::Error::other("Missing executable directory"))?,
        )
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(test)]
    command.args(&request.game_args);
    let mut child = match command.spawn() {
        Ok(child) => child,
        Err(error) => {
            let _ = write_phase(root, &Phase::Failed);
            return Err(error);
        }
    };
    let pid = child.id();
    let started = write_phase(root, &Phase::Started { pid });
    // A failed receipt write must not kill or abandon a possible running game.
    family.wait(&mut child)?;
    write_phase(root, &Phase::Finished { pid })?;
    started
}

#[cfg(not(any(windows, target_os = "linux")))]
fn supervise(root: &Path) -> io::Result<()> {
    let _ = read_request(root)?;
    Err(io::Error::other(
        "Verified launch families are not supported on this platform yet",
    ))
}

#[cfg(any(windows, target_os = "linux"))]
pub(super) fn start(
    base: &Path,
    installs: &Path,
    executable: &Path,
    game_uuid: String,
) -> io::Result<Launch> {
    let launch_id = uuid::Uuid::new_v4().to_string();
    fs::create_dir_all(base)?;
    let root = base.join(&launch_id);
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        fs::DirBuilder::new().mode(0o700).create(&root)?;
    }
    #[cfg(not(unix))]
    fs::create_dir(&root)?;
    let request = Request {
        version: 1,
        launch_id,
        game_uuid,
        install_root: installs.to_owned(),
        executable: executable.to_owned(),
        #[cfg(test)]
        game_args: Vec::new(),
    };
    super::install_recovery::atomic_write(
        &root.join("request.json"),
        &serde_json::to_vec(&request)?,
    )?;
    let mut command = Command::new(std::env::current_exe()?);
    command.arg(MODE).arg(&root);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000);
    }
    #[cfg(target_os = "linux")]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }
    start_with_command(&root, command)
}

pub(super) fn run_from_args() -> Option<i32> {
    let mut args = std::env::args_os().skip(1);
    if args.next().as_deref() != Some(std::ffi::OsStr::new(MODE)) {
        return None;
    }
    let result = match (args.next(), args.next()) {
        (Some(root), None) => supervise(Path::new(&root)),
        _ => Err(io::Error::other("Invalid launch supervisor invocation")),
    };
    Some(if result.is_ok() { 0 } else { 1 })
}

#[cfg(any(windows, target_os = "linux"))]
fn start_with_command(root: &Path, mut command: Command) -> io::Result<Launch> {
    let request = read_request(root)?;
    validate_executable(&request)?;
    let mut child = command
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()?;
    let result = (|| {
        let deadline = Instant::now() + Duration::from_secs(8);
        loop {
            match read_phase(root) {
                Ok(Phase::Prepared) => break,
                Ok(_) => {
                    return Err(io::Error::other(
                        "Supervisor preparation failed; no game was started",
                    ))
                }
                Err(error) if error.kind() == io::ErrorKind::NotFound => {}
                Err(error) => return Err(error),
            }
            if child.try_wait()?.is_some() || Instant::now() >= deadline {
                return Err(io::Error::other(
                    "Supervisor preparation failed; no game was started",
                ));
            }
            thread::sleep(Duration::from_millis(10));
        }
        super::install_recovery::atomic_write(&root.join("start"), request.launch_id.as_bytes())?;
        let deadline = Instant::now() + Duration::from_secs(8);
        loop {
            match read_phase(root) {
                Ok(Phase::Started { pid } | Phase::Finished { pid }) if pid > 0 => return Ok(pid),
                Ok(Phase::Failed) => return Err(io::Error::other("Game could not be started")),
                _ => {}
            }
            if child.try_wait()?.is_some() || Instant::now() >= deadline {
                return Err(io::Error::other(
                    "Launch status is uncertain. Check the game before retrying.",
                ));
            }
            thread::sleep(Duration::from_millis(10));
        }
    })();
    match result {
        Ok(pid) => Ok(Launch {
            child,
            pid,
            launch_id: request.launch_id,
        }),
        Err(error) => {
            // Never kill a possible game on an ambiguous reply or UI close.
            thread::spawn(move || {
                let _ = child.wait();
            });
            Err(error)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    pub(super) fn signal_wrapper_reaped() {
        if let Some(root) = std::env::var_os(ROOT_ENV) {
            fs::write(
                Path::new(&root).join("wrapper-reaped"),
                b"OS wait reaped direct wrapper",
            )
            .unwrap();
        }
    }
    const ROOT_ENV: &str = "ONEIRODEX_SUPERVISOR_OWNED_FIXTURE";
    fn fixture_command(root: &Path, name: &str) -> Command {
        let mut command = Command::new(std::env::current_exe().unwrap());
        command
            .args([
                "--ignored",
                "--exact",
                &format!("launch_supervisor::tests::{name}"),
                "--nocapture",
            ])
            .env(ROOT_ENV, root);
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x0800_0000);
        }
        command
    }
    fn fixture_root() -> PathBuf {
        let root = PathBuf::from(std::env::var_os(ROOT_ENV).expect("owned synthetic fixture only"));
        assert_eq!(
            fs::read(root.join("owned-marker")).unwrap(),
            b"DT006 supervisor fixture"
        );
        root
    }
    fn await_file(path: &Path) {
        let deadline = Instant::now() + Duration::from_secs(5);
        while !path.exists() {
            assert!(
                Instant::now() < deadline,
                "Missing fixture receipt: {}",
                path.display()
            );
            thread::sleep(Duration::from_millis(5));
        }
    }
    #[test]
    #[ignore = "Synthetic child role, invoked only by the bounded parent test"]
    fn guardian_fixture() {
        supervise(&fixture_root()).unwrap();
    }
    #[test]
    #[ignore = "Synthetic child role, invoked only by the bounded parent test"]
    #[allow(clippy::zombie_processes)] // Intentionally orphaned fixture; the guardian must reap it.
    fn wrapper_fixture() {
        let root = fixture_root();
        let mut command = fixture_command(&root, "leaf_fixture");
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x0900_0000); // Includes explicit breakaway.
        }
        #[cfg(target_os = "linux")]
        {
            use std::os::unix::process::CommandExt;
            command.process_group(0); // Escapes the guardian's process group.
        }
        let child = command
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        fs::write(root.join("leaf-pid"), child.id().to_string()).unwrap();
        // Return immediately. No process-tree snapshot can rely on this parent staying alive.
    }
    #[test]
    #[ignore = "Synthetic child role, invoked only by the bounded parent test"]
    fn leaf_fixture() {
        let root = fixture_root();
        fs::write(root.join("leaf-ready"), b"live").unwrap();
        let deadline = Instant::now() + Duration::from_secs(15);
        while !root.join("release-leaf").exists() && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(10));
        }
        fs::write(root.join("leaf-exited"), b"exited").unwrap();
    }
    struct ReleaseLeaf(PathBuf);
    impl Drop for ReleaseLeaf {
        fn drop(&mut self) {
            let _ = fs::write(self.0.join("release-leaf"), b"release");
        }
    }
    struct RunningFixture {
        launch: Launch,
        root: PathBuf,
    }
    impl std::ops::Deref for RunningFixture {
        type Target = Launch;
        fn deref(&self) -> &Launch {
            &self.launch
        }
    }
    impl std::ops::DerefMut for RunningFixture {
        fn deref_mut(&mut self) -> &mut Launch {
            &mut self.launch
        }
    }
    impl Drop for RunningFixture {
        fn drop(&mut self) {
            let _ = fs::write(self.root.join("release-leaf"), b"release");
            let _ = self.launch.child.wait(); // Fixture leaf has its own 15-second deadman.
        }
    }
    fn launch_fixture(root: &Path) -> RunningFixture {
        RunningFixture {
            launch: start_with_command(root, fixture_command(root, "guardian_fixture")).unwrap(),
            root: root.to_owned(),
        }
    }
    fn prepare_fixture(container: &Path) -> (PathBuf, Request) {
        let id = uuid::Uuid::new_v4().to_string();
        let root = container.join(&id);
        fs::create_dir(&root).unwrap();
        fs::write(root.join("owned-marker"), b"DT006 supervisor fixture").unwrap();
        let executable = std::env::current_exe().unwrap();
        let request = Request {
            version: 1,
            launch_id: id,
            game_uuid: "synthetic-game".into(),
            install_root: executable.parent().unwrap().to_owned(),
            executable,
            game_args: vec![
                "--ignored".into(),
                "--exact".into(),
                "launch_supervisor::tests::wrapper_fixture".into(),
                "--nocapture".into(),
            ],
        };
        fs::write(
            root.join("request.json"),
            serde_json::to_vec(&request).unwrap(),
        )
        .unwrap();
        (root, request)
    }
    fn await_finished(launch: &mut Launch) {
        let deadline = Instant::now() + Duration::from_secs(5);
        while launch.child.try_wait().unwrap().is_none() {
            assert!(Instant::now() < deadline);
            thread::sleep(Duration::from_millis(10));
        }
        assert!(launch.child.wait().unwrap().success());
    }
    #[test]
    fn independent_families_exclude_an_unrelated_live_process() {
        let container = tempfile::tempdir().unwrap();
        let (root_a, _) = prepare_fixture(container.path());
        let (root_b, _) = prepare_fixture(container.path());
        let (outsider, _) = prepare_fixture(container.path());
        let _release_a = ReleaseLeaf(root_a.clone());
        let _release_b = ReleaseLeaf(root_b.clone());
        let _release_outsider = ReleaseLeaf(outsider.clone());
        let mut unrelated = fixture_command(&outsider, "leaf_fixture")
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        await_file(&outsider.join("leaf-ready"));
        let mut a = launch_fixture(&root_a);
        let mut b = launch_fixture(&root_b);
        await_file(&root_a.join("leaf-ready"));
        await_file(&root_b.join("leaf-ready"));
        await_file(&root_a.join("wrapper-reaped"));
        await_file(&root_b.join("wrapper-reaped"));
        assert_ne!(a.launch_id, b.launch_id);
        fs::write(root_a.join("release-leaf"), b"release").unwrap();
        await_finished(&mut a);
        assert!(b.child.try_wait().unwrap().is_none());
        assert!(unrelated.try_wait().unwrap().is_none());
        fs::write(root_b.join("release-leaf"), b"release").unwrap();
        await_finished(&mut b);
        assert!(
            unrelated.try_wait().unwrap().is_none(),
            "unrelated live process cannot extend either family"
        );
        fs::write(outsider.join("release-leaf"), b"release").unwrap();
        assert!(unrelated.wait().unwrap().success());
    }
    #[test]
    fn malformed_or_moved_descriptor_cannot_start_a_game() {
        let container = tempfile::tempdir().unwrap();
        let (root, mut request) = prepare_fixture(container.path());
        request.launch_id = uuid::Uuid::new_v4().to_string();
        fs::write(
            root.join("request.json"),
            serde_json::to_vec(&request).unwrap(),
        )
        .unwrap();
        assert!(supervise(&root).is_err());
        assert!(!root.join("alive.lock").exists());
        assert!(!root.join("start").exists());
        assert!(!root.join("leaf-pid").exists());
        fs::write(root.join("request.json"), b"{ broken").unwrap();
        assert!(supervise(&root).is_err());
        assert!(!root.join("alive.lock").exists());
    }
    #[test]
    fn stale_started_record_and_unrelated_pid_do_not_establish_liveness() {
        let container = tempfile::tempdir().unwrap();
        let (root, request) = prepare_fixture(container.path());
        let pid = std::process::id(); // This unrelated process is definitely alive.
        fs::write(root.join("alive.lock"), b"").unwrap();
        write_phase(&root, &Phase::Started { pid }).unwrap();
        assert!(status(container.path(), pid, Some(&request.launch_id)).is_err());
        assert!(!status(container.path(), pid + 1, Some(&request.launch_id)).unwrap());
        assert!(!status(container.path(), pid, Some("../../another-launch")).unwrap());
        assert!(!status(
            container.path(),
            pid,
            Some(&uuid::Uuid::new_v4().to_string())
        )
        .unwrap());
        write_phase(&root, &Phase::Finished { pid }).unwrap();
        assert!(!status(container.path(), pid, Some(&request.launch_id)).unwrap());
        fs::write(root.join("phase.json"), b"{ broken").unwrap();
        assert!(status(container.path(), pid, Some(&request.launch_id)).is_err());
    }
    #[test]
    fn prepared_supervisor_requires_its_exact_start_authorization() {
        let container = tempfile::tempdir().unwrap();
        let (root, _) = prepare_fixture(container.path());
        let mut child = fixture_command(&root, "guardian_fixture")
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            await_file(&root.join("phase.json"));
            assert_eq!(read_phase(&root).unwrap(), Phase::Prepared);
            fs::write(root.join("start"), b"another-launch").unwrap();
            thread::sleep(Duration::from_millis(100));
            assert_eq!(read_phase(&root).unwrap(), Phase::Prepared);
            assert!(!root.join("leaf-pid").exists());
            assert!(child.try_wait().unwrap().is_none());
        }));
        // This owned guardian has never been authorized to create a game.
        child.kill().unwrap();
        child.wait().unwrap();
        let lease = File::open(root.join("alive.lock")).unwrap();
        lease
            .try_lock_exclusive()
            .expect("crashed guardian cannot retain a live lease");
        if let Err(error) = result {
            std::panic::resume_unwind(error);
        }
    }
    #[test]
    #[cfg(any(windows, target_os = "linux"))]
    fn fast_wrapper_retains_detached_child_until_it_exits() {
        let container = tempfile::tempdir().unwrap();
        let id = uuid::Uuid::new_v4().to_string();
        let root = container.path().join(&id);
        fs::create_dir(&root).unwrap();
        let root = root.as_path();
        let _cleanup = ReleaseLeaf(root.to_owned());
        fs::write(root.join("owned-marker"), b"DT006 supervisor fixture").unwrap();
        let executable = std::env::current_exe().unwrap();
        let request = Request {
            version: 1,
            launch_id: id,
            game_uuid: "synthetic-game".into(),
            install_root: executable.parent().unwrap().to_owned(),
            executable,
            game_args: vec![
                "--ignored".into(),
                "--exact".into(),
                "launch_supervisor::tests::wrapper_fixture".into(),
                "--nocapture".into(),
            ],
        };
        fs::write(
            root.join("request.json"),
            serde_json::to_vec(&request).unwrap(),
        )
        .unwrap();
        let mut launch = launch_fixture(root);
        await_file(&root.join("leaf-ready"));
        await_file(&root.join("wrapper-reaped"));
        assert!(launch.pid > 0);
        assert_eq!(launch.launch_id, request.launch_id);
        assert!(
            status(container.path(), launch.pid, Some(&launch.launch_id)).unwrap(),
            "a held lease and exact native receipt must identify this live launch"
        );
        assert!(!status(container.path(), launch.pid + 1, Some(&launch.launch_id)).unwrap());
        assert!(!status(container.path(), launch.pid, None).unwrap());
        assert!(
            launch.child.try_wait().unwrap().is_none(),
            "guardian must outlive the wrapper while its child lives"
        );
        assert!(matches!(read_phase(root).unwrap(), Phase::Started { .. }));
        let lease = File::open(root.join("alive.lock")).unwrap();
        assert_eq!(
            lease.try_lock_exclusive().unwrap_err().raw_os_error(),
            fs2::lock_contended_error().raw_os_error()
        );
        fs::write(root.join("release-leaf"), b"release").unwrap();
        await_file(&root.join("leaf-exited"));
        let deadline = Instant::now() + Duration::from_secs(5);
        while launch.child.try_wait().unwrap().is_none() {
            assert!(Instant::now() < deadline);
            thread::sleep(Duration::from_millis(10));
        }
        assert!(launch.child.wait().unwrap().success());
        assert_eq!(
            read_phase(root).unwrap(),
            Phase::Finished { pid: launch.pid }
        );
        lease
            .try_lock_exclusive()
            .expect("completed launch no longer holds the live lease");
        drop(lease);
        assert!(!status(container.path(), launch.pid, Some(&launch.launch_id)).unwrap());
    }
}
