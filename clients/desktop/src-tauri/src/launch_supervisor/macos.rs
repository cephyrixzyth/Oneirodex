//! Per-boot, per-launch coalition identity; no numeric PID establishes liveness.
#![cfg_attr(not(target_os = "macos"), allow(dead_code))]
use serde::{de::DeserializeOwned, Deserialize, Serialize};
use std::{fs, io, path::Path};

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Receipt {
    version: u32,
    launch_id: String,
    boot: String,
    coalition: u64,
    caller: u64,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Bootstrap {
    version: u32,
    launch_id: String,
    boot: String,
    caller: u64,
}

fn unavailable() -> io::Error {
    io::Error::other("Verified macOS launch tracking is unavailable")
}

fn label(id: &str) -> io::Result<String> {
    let uuid = uuid::Uuid::parse_str(id).map_err(|_| unavailable())?;
    if uuid.get_version_num() != 4 || uuid.to_string() != id {
        return Err(unavailable());
    }
    Ok(format!("com.oneirodex.launch.{id}"))
}

fn valid_boot(boot: &str) -> bool {
    uuid::Uuid::parse_str(boot).is_ok_and(|id| !id.is_nil() && id.to_string() == boot)
}

fn validate_receipt(r: &Receipt, id: &str, boot: &str) -> io::Result<()> {
    label(id)?;
    if r.version != 1
        || r.launch_id != id
        || !valid_boot(&r.boot)
        || r.boot != boot
        || r.coalition <= 1
        || r.caller <= 1
        || r.coalition == r.caller
    {
        return Err(unavailable());
    }
    Ok(())
}

fn read_json<T: DeserializeOwned>(path: &Path) -> io::Result<T> {
    let metadata = fs::symlink_metadata(path)?;
    if !metadata.is_file() || metadata.file_type().is_symlink() || metadata.len() > 1024 {
        return Err(unavailable());
    }
    serde_json::from_slice(&fs::read(path)?).map_err(|_| unavailable())
}

fn read_receipt(root: &Path, id: &str) -> io::Result<Receipt> {
    let r: Receipt = read_json(&root.join("macos-family.json"))?;
    validate_receipt(&r, id, &r.boot)?;
    Ok(r)
}

fn active_prefix(code: i32, counters: [u64; 2]) -> io::Result<u64> {
    if code != 0 || counters.contains(&u64::MAX) || counters[0] < counters[1] {
        Err(unavailable())
    } else {
        Ok(counters[0] - counters[1])
    }
}

fn classify(active: u64, before: bool, after: bool) -> io::Result<bool> {
    if before != after || (before && active == 0) {
        return Err(unavailable());
    }
    Ok(active > u64::from(before))
}

fn observed_status(
    receipt: &Receipt,
    id: &str,
    boot: &str,
    mut lease: impl FnMut() -> io::Result<bool>,
    query: impl FnOnce(u64) -> io::Result<u64>,
) -> io::Result<bool> {
    validate_receipt(receipt, id, boot)?;
    let before = lease()?;
    let active = query(receipt.coalition)?;
    classify(active, before, lease()?)
}

fn xml(value: &str) -> io::Result<String> {
    if value.chars().any(|c| {
        !(c == '\t' || c == '\n' || c == '\r' || c >= ' ') || c == '\u{fffe}' || c == '\u{ffff}'
    }) {
        return Err(unavailable());
    }
    Ok(value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&apos;")
        .replace('\r', "&#13;"))
}

fn plist(id: &str, args: &[String], fixture: Option<&Path>) -> io::Result<String> {
    let mut value = format!("<?xml version=\"1.0\" encoding=\"UTF-8\"?><plist version=\"1.0\"><dict><key>Label</key><string>{}</string><key>RunAtLoad</key><true/><key>KeepAlive</key><false/><key>AbandonProcessGroup</key><true/><key>ProgramArguments</key><array>", label(id)?);
    if args.is_empty() {
        return Err(unavailable());
    }
    for arg in args {
        value.push_str(&format!("<string>{}</string>", xml(arg)?));
    }
    value.push_str("</array><key>StandardOutPath</key><string>/dev/null</string><key>StandardErrorPath</key><string>/dev/null</string>");
    if let Some(root) = fixture {
        value.push_str(&format!("<key>EnvironmentVariables</key><dict><key>ONEIRODEX_SUPERVISOR_OWNED_FIXTURE</key><string>{}</string></dict>", xml(root.to_str().ok_or_else(unavailable)?)?));
    }
    value.push_str("</dict></plist>");
    Ok(value)
}

#[cfg(target_os = "macos")]
pub(super) use native::{bootstrap_command, cleanup, is_available, prepared, status, Family};
#[cfg(all(target_os = "macos", test))]
pub(super) use native::{fixture_loaded, kill_fixture, lease_held};

#[cfg(target_os = "macos")]
mod native {
    use super::*;
    use std::{
        ffi::{c_char, c_int, c_void},
        process::{Child, Command, Stdio},
        sync::OnceLock,
        thread,
        time::{Duration, Instant},
    };

    type Usage = unsafe extern "C" fn(u64, *mut c_void, usize) -> c_int;
    #[link(name = "proc")]
    extern "C" {
        fn proc_pidinfo(
            pid: c_int,
            flavor: c_int,
            arg: u64,
            buffer: *mut c_void,
            size: c_int,
        ) -> c_int;
    }
    extern "C" {
        fn dlsym(handle: *mut c_void, name: *const c_char) -> *mut c_void;
        fn sysctlbyname(
            name: *const c_char,
            old: *mut c_void,
            size: *mut usize,
            new: *mut c_void,
            new_size: usize,
        ) -> c_int;
        fn geteuid() -> u32;
    }

    fn uid() -> io::Result<u32> {
        let uid = unsafe { geteuid() };
        if uid == 0 {
            Err(unavailable())
        } else {
            Ok(uid)
        }
    }

    fn boot() -> io::Result<String> {
        let mut bytes = [0u8; 128];
        let mut size = bytes.len();
        let result = unsafe {
            sysctlbyname(
                c"kern.bootsessionuuid".as_ptr(),
                bytes.as_mut_ptr().cast(),
                &mut size,
                std::ptr::null_mut(),
                0,
            )
        };
        if result != 0 || size == 0 || size > bytes.len() {
            return Err(unavailable());
        }
        let text = std::str::from_utf8(&bytes[..size])
            .map_err(|_| unavailable())?
            .trim_end_matches('\0');
        let id = uuid::Uuid::parse_str(text).map_err(|_| unavailable())?;
        if id.is_nil() {
            return Err(unavailable());
        }
        Ok(id.to_string())
    }

    fn usage() -> io::Result<Usage> {
        static SYMBOL: OnceLock<Option<Usage>> = OnceLock::new();
        SYMBOL
            .get_or_init(|| {
                // Darwin RTLD_DEFAULT, declared in Apple's dyld/include/dlfcn.h.
                let symbol = unsafe {
                    dlsym(
                        (-2isize) as *mut c_void,
                        c"coalition_info_resource_usage".as_ptr(),
                    )
                };
                if symbol.is_null() {
                    None
                } else {
                    Some(unsafe { std::mem::transmute::<*mut c_void, Usage>(symbol) })
                }
            })
            .as_ref()
            .copied()
            .ok_or_else(unavailable)
    }

    fn count(coalition: u64) -> io::Result<u64> {
        if coalition <= 1 {
            return Err(unavailable());
        }
        let mut prefix = [u64::MAX; 2];
        let result = unsafe {
            usage()?(
                coalition,
                prefix.as_mut_ptr().cast(),
                std::mem::size_of_val(&prefix),
            )
        };
        // Same bounded prefix/ABI as R2073; errors never imply an ended family.
        active_prefix(result, prefix)
    }

    fn own() -> io::Result<u64> {
        uid()?;
        let mut ids = [0u64; 5];
        let pid = c_int::try_from(std::process::id()).map_err(|_| unavailable())?;
        let size = std::mem::size_of_val(&ids) as c_int;
        if unsafe { proc_pidinfo(pid, 20, 0, ids.as_mut_ptr().cast(), size) } != size || ids[0] <= 1
        {
            return Err(unavailable());
        }
        count(ids[0])?;
        Ok(ids[0])
    }

    pub(crate) fn is_available() -> bool {
        boot().is_ok() && own().is_ok()
    }

    pub(crate) fn prepared(root: &Path) -> io::Result<()> {
        let request = crate::launch_supervisor::read_request(root)?;
        let receipt = read_receipt(root, &request.launch_id)?;
        validate_receipt(&receipt, &request.launch_id, &boot()?)?;
        if !lease_held(root)? || count(receipt.coalition)? != 1 || !lease_held(root)? {
            return Err(unavailable());
        }
        Ok(())
    }

    pub(crate) fn lease_held(root: &Path) -> io::Result<bool> {
        crate::launch_supervisor::guardian_lease_held(root)
    }

    fn target(root: &Path) -> io::Result<String> {
        let request = crate::launch_supervisor::read_request(root)?;
        Ok(format!("gui/{}/{}", uid()?, label(&request.launch_id)?))
    }

    fn bounded_exit(mut command: Command) -> io::Result<std::process::ExitStatus> {
        let mut child = command
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()?;
        let deadline = Instant::now() + Duration::from_secs(5);
        loop {
            if let Some(exit) = child.try_wait()? {
                return Ok(exit);
            }
            if Instant::now() >= deadline {
                let _ = child.kill(); // Retained launchctl broker only, never a game.
                let _ = child.wait();
                return Err(unavailable());
            }
            thread::sleep(Duration::from_millis(10));
        }
    }

    pub(crate) fn cleanup(root: &Path) -> io::Result<()> {
        let mut command = Command::new("/bin/launchctl");
        command.arg("bootout").arg(target(root)?);
        if bounded_exit(command)?.success() {
            Ok(())
        } else {
            Err(unavailable())
        }
    }

    #[cfg(test)]
    pub(crate) fn fixture_loaded(root: &Path) -> io::Result<bool> {
        let mut command = Command::new("/bin/launchctl");
        command.arg("print").arg(target(root)?);
        let exit = bounded_exit(command)?;
        if exit.success() {
            Ok(true)
        } else if exit.code() == Some(113) {
            Ok(false)
        } else {
            Err(unavailable())
        }
    }

    #[cfg(test)]
    pub(crate) fn kill_fixture(root: &Path) -> io::Result<()> {
        let mut command = Command::new("/bin/launchctl");
        command.args(["kill", "SIGKILL"]).arg(target(root)?);
        if bounded_exit(command)?.success() {
            Ok(())
        } else {
            Err(unavailable())
        }
    }

    pub(crate) fn bootstrap_command(root: &Path, command: &Command) -> io::Result<Command> {
        let request = crate::launch_supervisor::read_request(root)?;
        for name in ["start", "phase.json", "alive.lock", "macos-bootstrap.json"] {
            if root.join(name).try_exists()? {
                return Err(unavailable());
            }
        }
        let descriptor = Bootstrap {
            version: 1,
            launch_id: request.launch_id.clone(),
            boot: boot()?,
            caller: own()?,
        };
        let args = std::iter::once(command.get_program())
            .chain(command.get_args())
            .map(|s| s.to_str().map(str::to_owned).ok_or_else(unavailable))
            .collect::<io::Result<Vec<_>>>()?;
        #[cfg(test)]
        let fixture = command
            .get_envs()
            .find(|(k, _)| *k == "ONEIRODEX_SUPERVISOR_OWNED_FIXTURE")
            .and_then(|(_, v)| v)
            .map(Path::new);
        #[cfg(not(test))]
        let fixture = None;
        crate::install_recovery::atomic_write(
            &root.join("macos-bootstrap.json"),
            &serde_json::to_vec(&descriptor)?,
        )?;
        crate::install_recovery::atomic_write(
            &root.join("job.plist"),
            plist(&request.launch_id, &args, fixture)?.as_bytes(),
        )?;
        let mut broker = Command::new("/bin/launchctl");
        broker
            .arg("bootstrap")
            .arg(format!("gui/{}", uid()?))
            .arg(root.join("job.plist"));
        Ok(broker)
    }

    pub(crate) struct Family {
        coalition: u64,
    }
    impl Family {
        pub(crate) fn new(root: &Path) -> io::Result<Self> {
            let request = crate::launch_supervisor::read_request(root)?;
            let b: Bootstrap = read_json(&root.join("macos-bootstrap.json"))?;
            let boot = boot()?;
            let coalition = own()?;
            let receipt = Receipt {
                version: b.version,
                launch_id: b.launch_id,
                boot: b.boot,
                coalition,
                caller: b.caller,
            };
            validate_receipt(&receipt, &request.launch_id, &boot)?;
            if count(coalition)? != 1 {
                return Err(unavailable());
            }
            crate::install_recovery::atomic_write(
                &root.join("macos-family.json"),
                &serde_json::to_vec(&receipt)?,
            )?;
            Ok(Self { coalition })
        }

        pub(crate) fn wait(&self, child: &mut Child) -> io::Result<()> {
            #[cfg(test)]
            let mut signaled = false;
            loop {
                let reaped = child.try_wait()?.is_some();
                #[cfg(test)]
                if reaped && !signaled {
                    crate::launch_supervisor::tests::signal_wrapper_reaped();
                    signaled = true;
                }
                let active = count(self.coalition)?;
                if active == 0 {
                    return Err(unavailable());
                }
                if reaped && active == 1 {
                    return Ok(());
                }
                thread::sleep(Duration::from_millis(100));
            }
        }
    }

    pub(crate) fn status(root: &Path, pid: u32) -> io::Result<bool> {
        let request = crate::launch_supervisor::read_request(root)?;
        let receipt = read_receipt(root, &request.launch_id)?;
        let running = observed_status(
            &receipt,
            &request.launch_id,
            &boot()?,
            || lease_held(root),
            count,
        )?;
        match crate::launch_supervisor::read_phase(root)? {
            crate::launch_supervisor::Phase::Finished { pid: recorded } if recorded == pid => {
                return Ok(false)
            }
            crate::launch_supervisor::Phase::Started { pid: recorded } if recorded == pid => {}
            _ => return Err(unavailable()),
        }
        if !running && !lease_held(root)? {
            // Known empty retained group after guardian loss; never on API error.
            crate::launch_supervisor::write_phase(
                root,
                &crate::launch_supervisor::Phase::Finished {
                    pid: match crate::launch_supervisor::read_phase(root)? {
                        crate::launch_supervisor::Phase::Started { pid } => pid,
                        _ => return Ok(false),
                    },
                },
            )?;
            let _ = cleanup(root);
        }
        Ok(running)
    }

    #[cfg(test)]
    mod tests {
        use super::*;
        #[test]
        fn rust_native_boot_and_coalition_abi_are_available() {
            let first = boot().unwrap();
            assert_eq!(first, boot().unwrap());
            assert!(valid_boot(&first));
            assert!(own().unwrap() > 1);
            assert!(count(own().unwrap()).unwrap() > 0);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn receipt() -> Receipt {
        Receipt {
            version: 1,
            launch_id: "d6c50901-8d18-4993-bfcf-19431faf4a60".into(),
            boot: "13c78c74-a26c-45b0-8d46-874b9adaeb35".into(),
            coalition: 200,
            caller: 99,
        }
    }

    #[test]
    fn native_counter_errors_and_underflow_are_not_ended_games() {
        assert_eq!(active_prefix(0, [9, 7]).unwrap(), 2);
        for (code, counts) in [
            (1, [9, 7]),
            (0, [u64::MAX, 0]),
            (0, [0, u64::MAX]),
            (0, [3, 4]),
        ] {
            assert!(active_prefix(code, counts).is_err());
        }
    }

    #[test]
    fn exact_boot_launch_and_distinct_coalition_are_required_before_query() {
        let original = receipt();
        for bad in [
            Receipt {
                boot: uuid::Uuid::new_v4().to_string(),
                ..original.clone()
            },
            Receipt {
                coalition: 99,
                ..original.clone()
            },
            Receipt {
                coalition: 1,
                ..original.clone()
            },
            Receipt {
                version: 2,
                ..original.clone()
            },
        ] {
            assert!(observed_status(
                &bad,
                &original.launch_id,
                &original.boot,
                || panic!("invalid identity reached lease"),
                |_| panic!("invalid identity reached kernel")
            )
            .is_err());
        }
        assert!(observed_status(
            &original,
            "../another-launch",
            &original.boot,
            || panic!("invalid launch reached lease"),
            |_| panic!("invalid launch reached kernel")
        )
        .is_err());
    }

    #[test]
    fn guardian_baseline_and_changes_do_not_adopt_an_unrelated_game() {
        assert!(classify(2, true, true).unwrap());
        assert!(!classify(1, true, true).unwrap());
        assert!(classify(1, false, false).unwrap());
        assert!(!classify(0, false, false).unwrap());
        assert!(classify(0, true, true).is_err());
        assert!(classify(1, true, false).is_err());
        let r = receipt();
        assert!(observed_status(
            &r,
            &r.launch_id,
            &r.boot,
            || Ok(false),
            |_| Err(std::io::Error::other("query unavailable"))
        )
        .is_err());
    }

    #[test]
    fn plist_escapes_arguments_and_does_not_copy_the_app_environment() {
        let r = receipt();
        let xml = plist(
            &r.launch_id,
            &["/tmp/Game<&\"'名.app/binary".into(), "argument".into()],
            None,
        )
        .unwrap();
        assert!(xml.contains("Game&lt;&amp;&quot;&apos;名.app"));
        assert!(xml.contains("<key>AbandonProcessGroup</key><true/>"));
        assert!(xml.contains("<key>KeepAlive</key><false/>"));
        assert!(!xml.contains("EnvironmentVariables"));
        assert!(plist("../other", &["/bin/true".into()], None).is_err());
        assert!(plist(&r.launch_id, &["/tmp/bad\0value".into()], None).is_err());
    }

    #[test]
    fn plist_preserves_carriage_return_in_a_posix_path() {
        let r = receipt();
        let encoded = plist(&r.launch_id, &["/tmp/line\rname/binary".into()], None).unwrap();
        assert!(encoded.contains("/tmp/line&#13;name/binary"));
        assert!(!encoded.contains('\r'));
    }

    #[test]
    fn bounded_strict_receipt_rejects_corruption_and_unknown_fields() {
        let dir = tempfile::tempdir().unwrap();
        let r = receipt();
        std::fs::write(
            dir.path().join("macos-family.json"),
            serde_json::to_vec(&r).unwrap(),
        )
        .unwrap();
        assert_eq!(
            read_receipt(dir.path(), &r.launch_id).unwrap().coalition,
            200
        );
        for raw in [
            b"{".to_vec(),
            vec![b' '; 1025],
            b"{\"unknown\":true}".to_vec(),
        ] {
            std::fs::write(dir.path().join("macos-family.json"), raw).unwrap();
            assert!(read_receipt(dir.path(), &r.launch_id).is_err());
        }
    }
}
