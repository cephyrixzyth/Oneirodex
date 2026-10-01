use keyring::Entry;
use serde::{Deserialize, Serialize};
use std::fs::{self, File};
use std::io::{copy, Write};
use std::net::{Ipv4Addr, Ipv6Addr};
use std::path::{Path, PathBuf};
use tauri::Manager;
use url::{Host, Url};
use zip::ZipArchive;
mod install_recovery;

/// Fallback service name for OS credential store entries when the bundle
/// identifier is unavailable (tests, unbundled dev runs).
const SECURE_STORE_SERVICE_FALLBACK: &str = "com.oneirodex.desktop";

/// Service name for OS credential store entries (Windows Credential Manager,
/// macOS Keychain, Secret Service).
///
/// This is the app's own bundle identifier, not a constant: the full companion
/// (`com.oneirodex.desktop`) and the thin client (`com.oneirodex.thin`) ship as
/// separate apps with separate app-data directories, and they must not share a
/// credential. They did — both wrote the account `api_token` under the
/// companion's service — so installing thin on a companion PC overwrote the
/// companion's token with a thin-preset one that carries no `write:download`,
/// and Download/Install then failed on scope with nothing to point at.
fn secure_store_service(app: &tauri::AppHandle) -> String {
    let identifier = app.config().identifier.trim().to_string();
    if identifier.is_empty() {
        return SECURE_STORE_SERVICE_FALLBACK.to_string();
    }
    identifier
}

#[derive(Debug, Serialize, Deserialize, Default, Clone)]
pub struct AppConfig {
    pub base_url: String,
    pub token: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct LifecycleRecord {
    pub game_uuid: String,
    pub state: String,
}

#[derive(Debug, Serialize, Deserialize, Default, Clone)]
pub struct LifecycleRegistryFile {
    pub records: Vec<LifecycleRecord>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct InstallRecord {
    pub archive_path: String,
    pub extract_path: String,
    pub exe_path: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub retained_path: Option<String>,
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub pending_uninstall: bool,
}

#[derive(Debug, Serialize, Deserialize, Default, Clone)]
pub struct InstallsFile {
    pub installs: std::collections::HashMap<String, InstallRecord>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ExtractZipResult {
    pub extract_path: String,
    pub exe_path: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct LaunchGameResult {
    pub pid: u32,
    pub exe_path: String,
    pub resolved_exe_path: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct RevealPathResult {
    pub path: String,
    pub revealed_as: String,
}

fn app_data_dir(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|error| error.to_string())?;
    fs::create_dir_all(&dir).map_err(|error| error.to_string())?;
    Ok(dir)
}

fn config_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    Ok(app_data_dir(app)?.join("config.json"))
}

fn lifecycle_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    Ok(app_data_dir(app)?.join("lifecycle.json"))
}

fn installs_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    Ok(app_data_dir(app)?.join("installs.json"))
}

fn resolve_subdir(app: &tauri::AppHandle, subdir: &str) -> Result<PathBuf, String> {
    let dir = app_data_dir(app)?.join(subdir);
    fs::create_dir_all(&dir).map_err(|error| error.to_string())?;
    Ok(dir)
}

fn installs_root(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    resolve_subdir(app, "installs")
}

fn canonicalize_path(path: &Path) -> Result<PathBuf, String> {
    if path.exists() {
        return path.canonicalize().map_err(|error| error.to_string());
    }

    if let Some(parent) = path.parent() {
        if parent.as_os_str().is_empty() {
            return Ok(path.to_path_buf());
        }
        let canonical_parent = parent.canonicalize().map_err(|error| error.to_string())?;
        if let Some(file_name) = path.file_name() {
            return Ok(canonical_parent.join(file_name));
        }
    }

    Ok(path.to_path_buf())
}

/// Canonicalize `path` and `root` and require `path` to sit inside `root`.
///
/// `Path::starts_with` is reflexive, so the plain check also accepts the root
/// itself. That is fine for anything that reads or writes *into* the root, but
/// fatal for an operation that wipes or removes its target: a game id of `.`
/// would make the target the whole installs directory. `strict` closes that by
/// refusing the root itself.
fn check_path_under_root(path: &Path, root: &Path, strict: bool) -> Result<(), String> {
    let canonical_root = root.canonicalize().map_err(|error| error.to_string())?;
    let canonical_path = canonicalize_path(path)?;
    if !canonical_path.starts_with(&canonical_root) {
        return Err("Path is outside allowed app directory".into());
    }
    if strict && canonical_path == canonical_root {
        return Err("Path must be inside an app directory, not the directory itself".into());
    }
    Ok(())
}

fn check_path_under_any_root(path: &Path, roots: &[&Path], strict: bool) -> Result<(), String> {
    for root in roots {
        if check_path_under_root(path, root, strict).is_ok() {
            return Ok(());
        }
    }
    Err("Path is outside allowed app directories".into())
}

/// `path` is the root or anything below it — for reads and writes into the root.
fn ensure_path_under_root(path: &Path, root: &Path) -> Result<(), String> {
    check_path_under_root(path, root, false)
}

fn ensure_path_under_any_root(path: &Path, roots: &[&Path]) -> Result<(), String> {
    check_path_under_any_root(path, roots, false)
}

/// `path` is strictly below the root (never the root itself). Use for every
/// destructive operation: extract-with-wipe, remove, rename, uninstall.
fn ensure_path_strictly_under_root(path: &Path, root: &Path) -> Result<(), String> {
    check_path_under_root(path, root, true)
}

fn ensure_path_strictly_under_any_root(path: &Path, roots: &[&Path]) -> Result<(), String> {
    check_path_under_any_root(path, roots, true)
}

/// Is this file the sort of thing we can hand to `Command::new`?
///
/// Windows answers with the `.exe` extension. Unix has no extension to read, so
/// the executable bit is the only real signal — which is exactly why
/// `extract_zip_archive` restores it. Shared libraries carry that bit too and
/// are never an entry point, so they are excluded by extension.
#[cfg(windows)]
fn is_launchable_file(path: &Path) -> bool {
    path.extension()
        .is_some_and(|ext| ext.eq_ignore_ascii_case("exe"))
}

#[cfg(unix)]
fn is_launchable_file(path: &Path) -> bool {
    use std::os::unix::fs::PermissionsExt;

    if let Some(ext) = path.extension() {
        // Executable-bit-carrying files that are never the entry point.
        for skip in ["so", "dylib", "a", "o", "bundle"] {
            if ext.eq_ignore_ascii_case(skip) {
                return false;
            }
        }
    }

    fs::metadata(path)
        .map(|meta| meta.permissions().mode() & 0o111 != 0)
        .unwrap_or(false)
}

#[cfg(not(any(unix, windows)))]
fn is_launchable_file(_path: &Path) -> bool {
    false
}

fn find_likely_exe(dir: &Path, max_depth: u32) -> Option<String> {
    find_likely_exe_inner(dir, 0, max_depth)
}

fn find_likely_exe_inner(dir: &Path, depth: u32, max_depth: u32) -> Option<String> {
    if depth > max_depth {
        return None;
    }

    let entries = fs::read_dir(dir).ok()?;
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_file() && is_launchable_file(&path) {
            return Some(path.to_string_lossy().into_owned());
        }
    }

    if depth >= max_depth {
        return None;
    }

    let entries = fs::read_dir(dir).ok()?;
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            if let Some(found) = find_likely_exe_inner(&path, depth + 1, max_depth) {
                return Some(found);
            }
        }
    }

    None
}

// Each `cfg` arm is a full `return` so the arms stay mutually exclusive without
// tripping "unreachable expression" on the platform whose arm is compiled last;
// clippy reads the explicit `return` as needless, but dropping it makes the
// multi-arm shape fragile. Scoped allow rather than a crate-wide one.
#[allow(clippy::needless_return)]
fn check_process_running(pid: u32) -> bool {
    if pid == 0 {
        return false;
    }

    #[cfg(unix)]
    {
        use std::process::Command;
        return Command::new("kill")
            .args(["-0", &pid.to_string()])
            .status()
            .map(|status| status.success())
            .unwrap_or(false);
    }

    #[cfg(windows)]
    {
        use std::process::Command;
        return Command::new("tasklist")
            .args(["/FI", &format!("PID eq {pid}"), "/NH"])
            .output()
            .map(|output| String::from_utf8_lossy(&output.stdout).contains(&pid.to_string()))
            .unwrap_or(false);
    }

    #[cfg(not(any(unix, windows)))]
    {
        let _ = pid;
        false
    }
}

/// Is this IPv4 address on the local machine or local network?
/// 127/8, 10/8, 172.16/12, 192.168/16 and 169.254/16.
fn is_private_or_loopback_ipv4(ip: &Ipv4Addr) -> bool {
    ip.is_loopback() || ip.is_private() || ip.is_link_local()
}

/// Same for IPv6: `::1`, unique-local `fc00::/7`, link-local `fe80::/10`, and an
/// IPv4-mapped address (`::ffff:a.b.c.d`) whose embedded IPv4 is itself local.
fn is_private_or_loopback_ipv6(ip: &Ipv6Addr) -> bool {
    if let Some(mapped) = ip.to_ipv4_mapped() {
        return is_private_or_loopback_ipv4(&mapped);
    }
    let first = ip.segments()[0];
    ip.is_loopback() || (first & 0xfe00) == 0xfc00 || (first & 0xffc0) == 0xfe80
}

/// Does this host name a machine on the user's own network?
///
/// Besides the literal local address ranges: `*.local` (mDNS) and a bare
/// single-label name such as `nas` or `localhost`, which only resolve through the
/// local resolver / search domain. Anything with a public-looking dotted name is
/// not local, however much like a LAN address it reads (`192.168.1.1.evil.com`).
fn is_private_or_loopback_host(host: &Host<&str>) -> bool {
    match host {
        Host::Ipv4(ip) => is_private_or_loopback_ipv4(ip),
        Host::Ipv6(ip) => is_private_or_loopback_ipv6(ip),
        Host::Domain(domain) => {
            let name = domain.trim_end_matches('.').to_ascii_lowercase();
            match name.strip_suffix(".local") {
                Some(label) => !label.is_empty(),
                None => !name.is_empty() && !name.contains('.'),
            }
        }
    }
}

/// Validate the server base URL before it is written to `config.json`.
///
/// The companion sends its API token as a Bearer header on every request, so a
/// plain `http://` server on the open internet would expose the token to anyone
/// on the path. `https://` is always accepted; `http://` only for loopback and
/// private-LAN hosts; every other scheme is refused. An empty string clears the
/// saved URL and is allowed. The TypeScript client applies the same policy before
/// it ever sends a request — this is the backstop for anything that reaches
/// `save_config` without going through it.
fn validate_server_base_url(raw: &str) -> Result<(), String> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return Ok(());
    }
    let url = Url::parse(trimmed).map_err(|_| {
        "Server URL is not a valid URL. Start it with https:// (or http:// for a server on your own network).".to_string()
    })?;
    match url.scheme() {
        "https" => Ok(()),
        "http" => {
            if url
                .host()
                .is_some_and(|host| is_private_or_loopback_host(&host))
            {
                return Ok(());
            }
            Err(format!(
                "Refusing http:// for {}: your API token would be sent unencrypted. Use an https:// server URL (plain http:// is only allowed for localhost, LAN addresses and .local names).",
                url.host_str().unwrap_or("this server")
            ))
        }
        _ => Err(
            "Server URL must start with https:// (or http:// for a server on your own network)."
                .to_string(),
        ),
    }
}

/// Apply `validate_server_base_url` to a `save_config` request.
///
/// A URL that is already on disk may be re-saved unchanged: that is how the
/// legacy plaintext token gets scrubbed from `config.json` on first load, and it
/// creates no new exposure (the TypeScript client still refuses to use the URL).
/// Any *new* URL has to pass the policy.
fn validate_config_base_url(config_file: &Path, requested: &str) -> Result<(), String> {
    let persisted = fs::read_to_string(config_file)
        .ok()
        .and_then(|data| serde_json::from_str::<AppConfig>(&data).ok())
        .map(|config| config.base_url);
    if persisted.as_deref().map(str::trim) == Some(requested.trim()) {
        return Ok(());
    }
    validate_server_base_url(requested)
}

#[tauri::command]
fn load_config(app: tauri::AppHandle) -> Result<AppConfig, String> {
    let path = config_path(&app)?;
    if !path.exists() {
        return Ok(AppConfig::default());
    }

    let data = fs::read_to_string(path).map_err(|error| error.to_string())?;
    serde_json::from_str(&data).map_err(|error| error.to_string())
}

#[tauri::command]
fn save_config(app: tauri::AppHandle, config: AppConfig) -> Result<(), String> {
    let path = config_path(&app)?;
    validate_config_base_url(&path, &config.base_url)?;
    // Never persist API tokens in plaintext JSON — secrets live in the OS store.
    let sanitized = AppConfig {
        base_url: config.base_url,
        token: None,
    };
    let data = serde_json::to_string_pretty(&sanitized).map_err(|error| error.to_string())?;
    fs::write(path, data).map_err(|error| error.to_string())
}

fn secure_entry(app: &tauri::AppHandle, account: &str) -> Result<Entry, String> {
    Entry::new(&secure_store_service(app), account).map_err(|error| error.to_string())
}

#[tauri::command]
fn secure_store_get(app: tauri::AppHandle, account: String) -> Result<Option<String>, String> {
    let entry = secure_entry(&app, &account)?;
    match entry.get_password() {
        Ok(secret) => Ok(Some(secret)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(error) => Err(error.to_string()),
    }
}

#[tauri::command]
fn secure_store_set(app: tauri::AppHandle, account: String, secret: String) -> Result<(), String> {
    let entry = secure_entry(&app, &account)?;
    entry
        .set_password(&secret)
        .map_err(|error| error.to_string())
}

#[tauri::command]
fn secure_store_delete(app: tauri::AppHandle, account: String) -> Result<(), String> {
    let entry = secure_entry(&app, &account)?;
    match entry.delete_credential() {
        Ok(()) => Ok(()),
        Err(keyring::Error::NoEntry) => Ok(()),
        Err(error) => Err(error.to_string()),
    }
}

#[tauri::command]
fn load_lifecycle_registry(app: tauri::AppHandle) -> Result<LifecycleRegistryFile, String> {
    let path = lifecycle_path(&app)?;
    if !path.exists() {
        return Ok(LifecycleRegistryFile::default());
    }

    let data = fs::read_to_string(path).map_err(|error| error.to_string())?;
    serde_json::from_str(&data).map_err(|error| error.to_string())
}

#[tauri::command]
fn save_lifecycle_registry(
    app: tauri::AppHandle,
    registry: LifecycleRegistryFile,
) -> Result<(), String> {
    let path = lifecycle_path(&app)?;
    let data = serde_json::to_string_pretty(&registry).map_err(|error| error.to_string())?;
    fs::write(path, data).map_err(|error| error.to_string())
}

#[tauri::command]
fn load_installs(app: tauri::AppHandle) -> Result<InstallsFile, String> {
    let path = installs_path(&app)?;
    if !path.exists() {
        return Ok(InstallsFile::default());
    }

    let data = fs::read_to_string(path).map_err(|error| error.to_string())?;
    serde_json::from_str(&data).map_err(|error| error.to_string())
}

#[tauri::command]
fn save_installs(app: tauri::AppHandle, installs_file: InstallsFile) -> Result<(), String> {
    let path = installs_path(&app)?;
    let data = serde_json::to_string_pretty(&installs_file).map_err(|error| error.to_string())?;
    install_recovery::atomic_write(&path, data.as_bytes()).map_err(|error| error.to_string())
}

#[tauri::command]
fn retain_install_files(app: tauri::AppHandle, from: String, to: String) -> Result<(), String> {
    let root = installs_root(&app)?;
    let source = PathBuf::from(from);
    let destination = PathBuf::from(to);
    ensure_path_under_root(&source, &root)?;
    ensure_path_under_root(&destination, &root)?;
    let source = source.canonicalize().map_err(|error| error.to_string())?;
    let destination = destination
        .canonicalize()
        .map_err(|error| error.to_string())?;
    if source.starts_with(&destination) || destination.starts_with(&source) {
        return Err("Update directories must be separate".into());
    }
    install_recovery::retain_missing(&source, &destination).map_err(|error| error.to_string())
}

#[tauri::command]
fn preserve_install_files(
    app: tauri::AppHandle,
    path: String,
    backup_path: String,
) -> Result<Option<String>, String> {
    let root = installs_root(&app)?;
    let source = PathBuf::from(&path);
    let backup = PathBuf::from(&backup_path);
    ensure_path_under_root(&source, &root)?;
    ensure_path_under_root(&backup, &root)?;
    if !source.exists() {
        return Ok(None);
    }
    let source = source.canonicalize().map_err(|error| error.to_string())?;
    let backup = canonicalize_path(&backup)?;
    if backup.exists()
        || source == root.canonicalize().map_err(|error| error.to_string())?
        || backup.starts_with(&source)
    {
        return Err("Invalid install backup destination".into());
    }
    fs::create_dir(&backup).map_err(|error| error.to_string())?;
    install_recovery::retain_missing(&source, &backup).map_err(|error| error.to_string())?;
    Ok(Some(backup_path))
}

#[tauri::command]
fn restore_install_snapshot(
    app: tauri::AppHandle,
    from: String,
    to: String,
) -> Result<ExtractZipResult, String> {
    let root = installs_root(&app)?;
    let source = PathBuf::from(from);
    let destination = PathBuf::from(to);
    ensure_path_under_root(&source, &root)?;
    ensure_path_under_root(&destination, &root)?;
    let source = source.canonicalize().map_err(|error| error.to_string())?;
    let destination = canonicalize_path(&destination)?;
    if destination.exists() || destination.starts_with(&source) || source.starts_with(&destination)
    {
        return Err("Restore destination must be a separate new directory".into());
    }
    fs::create_dir(&destination).map_err(|error| error.to_string())?;
    install_recovery::retain_missing(&source, &destination).map_err(|error| error.to_string())?;
    // `canonicalize` hands back `\\?\C:\…` on Windows. That string ends up in the
    // install record and later in "Show in Explorer", which refuses device-style
    // paths — give the record the ordinary drive path instead.
    Ok(ExtractZipResult {
        extract_path: user_facing_path(&destination.to_string_lossy()),
        exe_path: find_likely_exe(&destination, 2).map(|exe| user_facing_path(&exe)),
    })
}

/// Strip the Win32 verbatim prefix from a drive path (`\\?\C:\x` -> `C:\x`).
/// Verbatim UNC (`\\?\UNC\host\share`) and every other shape is returned as is.
fn user_facing_path(path: &str) -> String {
    if let Some(rest) = path.strip_prefix(r"\\?\") {
        let bytes = rest.as_bytes();
        if bytes.len() >= 3
            && bytes[0].is_ascii_alphabetic()
            && bytes[1] == b':'
            && bytes[2] == b'\\'
        {
            return rest.to_string();
        }
    }
    path.to_string()
}

#[tauri::command]
fn get_app_subdir(app: tauri::AppHandle, subdir: String) -> Result<String, String> {
    resolve_subdir(&app, &subdir).map(|path| path.to_string_lossy().into_owned())
}

#[tauri::command]
fn write_file_bytes(app: tauri::AppHandle, path: String, bytes: Vec<u8>) -> Result<(), String> {
    let downloads = resolve_subdir(&app, "downloads")?;
    let cheats = resolve_subdir(&app, "cheats")?;
    let patches = resolve_subdir(&app, "patches")?;
    let mods = resolve_subdir(&app, "mods")?;
    let file_path = PathBuf::from(&path);
    ensure_path_under_any_root(&file_path, &[&downloads, &cheats, &patches, &mods])?;
    if let Some(parent) = file_path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }

    let mut file = File::create(&file_path).map_err(|error| error.to_string())?;
    file.write_all(&bytes).map_err(|error| error.to_string())
}

#[tauri::command]
fn append_file_bytes(app: tauri::AppHandle, path: String, bytes: Vec<u8>) -> Result<(), String> {
    use std::fs::OpenOptions;

    let downloads = resolve_subdir(&app, "downloads")?;
    let file_path = PathBuf::from(&path);
    ensure_path_under_root(&file_path, &downloads)?;
    if let Some(parent) = file_path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }

    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&file_path)
        .map_err(|error| error.to_string())?;
    file.write_all(&bytes).map_err(|error| error.to_string())
}

#[tauri::command]
fn extract_zip_archive(
    app: tauri::AppHandle,
    archive_path: String,
    dest_dir: String,
) -> Result<ExtractZipResult, String> {
    let downloads = resolve_subdir(&app, "downloads")?;
    let installs = resolve_subdir(&app, "installs")?;
    extract_zip_within_roots(
        Path::new(&archive_path),
        Path::new(&dest_dir),
        &downloads,
        &installs,
    )
}

/// The containment rules of `extract_zip_archive`, without the `AppHandle`.
///
/// `extract_zip_to_dir` deletes `destination` before extracting, so the
/// destination must be strictly *below* the installs root: a destination equal
/// to the root (a game id of `.`) would wipe every installed game.
fn extract_zip_within_roots(
    archive: &Path,
    destination: &Path,
    downloads: &Path,
    installs: &Path,
) -> Result<ExtractZipResult, String> {
    ensure_path_under_root(archive, downloads)?;
    ensure_path_strictly_under_root(destination, installs)?;
    extract_zip_to_dir(archive, destination)
}

/// Extract every entry of `archive` under `destination`, restoring unix
/// permission bits, and return the extract path plus a best-guess entry point.
///
/// Split out from `extract_zip_archive` so the zip-slip / `enclosed_name()`
/// handling is unit-testable without a `tauri::AppHandle`. The command wrapper
/// still owns the app-root containment check on `archive` / `destination`.
fn extract_zip_to_dir(archive: &Path, destination: &Path) -> Result<ExtractZipResult, String> {
    if !archive.is_file() {
        return Err(format!("Archive not found: {}", archive.display()));
    }

    if destination.exists() {
        remove_path_inner(destination)?;
    }
    fs::create_dir_all(destination).map_err(|error| error.to_string())?;

    let file = File::open(archive).map_err(|error| error.to_string())?;
    let mut zip = ZipArchive::new(file).map_err(|error| error.to_string())?;

    for index in 0..zip.len() {
        let mut entry = zip.by_index(index).map_err(|error| error.to_string())?;
        // `enclosed_name()` returns `None` for any entry name that would escape
        // the destination (`..` segments, absolute paths, drive letters), so a
        // zip-slip entry is skipped outright.
        let entry_path = match entry.enclosed_name() {
            Some(path) => destination.join(path),
            None => continue,
        };

        // Defence in depth: `enclosed_name()` already blocks traversal, but a
        // future swap of the zip crate must not be able to silently reintroduce
        // zip-slip. A join that lands outside `destination` is dropped.
        if !entry_path.starts_with(destination) {
            continue;
        }

        if entry.name().ends_with('/') {
            fs::create_dir_all(&entry_path).map_err(|error| error.to_string())?;
            continue;
        }

        if let Some(parent) = entry_path.parent() {
            fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }

        let mut out = File::create(&entry_path).map_err(|error| error.to_string())?;
        copy(&mut entry, &mut out).map_err(|error| error.to_string())?;

        // Restore the archived permission bits on unix. Without this every
        // extracted file lands 0644 and `launch_game` fails with "permission
        // denied" on the one file that was supposed to be the entry point —
        // and `find_likely_exe` cannot see it either, because the executable
        // bit is the only thing that marks an entry point on a platform with
        // no `.exe` extension. Archives authored on Windows carry no unix mode
        // at all; those stay 0644, which is correct — a Windows build is not
        // launchable here regardless.
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            if let Some(mode) = entry.unix_mode() {
                fs::set_permissions(&entry_path, fs::Permissions::from_mode(mode))
                    .map_err(|error| error.to_string())?;
            }
        }
    }

    let exe_path = find_likely_exe(destination, 2);
    Ok(ExtractZipResult {
        extract_path: destination.to_string_lossy().into_owned(),
        exe_path,
    })
}

#[tauri::command]
fn launch_game(
    app: tauri::AppHandle,
    game_uuid: String,
    exe_path: Option<String>,
    extract_path: String,
) -> Result<LaunchGameResult, String> {
    let _ = game_uuid;
    let installs = installs_root(&app)?;
    let extract = PathBuf::from(&extract_path);
    ensure_path_under_root(&extract, &installs)?;

    let had_exe_path = exe_path.is_some();
    let resolved = if let Some(exe) = exe_path {
        let candidate = PathBuf::from(&exe);
        ensure_path_under_root(&candidate, &installs)?;
        if !candidate.is_file() {
            return Err(format!("Executable not found: {exe}"));
        }
        candidate
    } else {
        find_likely_exe(&extract, 2)
            .map(PathBuf::from)
            .ok_or_else(|| "No executable found in install directory".to_string())?
    };

    ensure_path_under_root(&resolved, &installs)?;

    let working_dir = resolved
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_else(|| extract.clone());

    let child = std::process::Command::new(&resolved)
        .current_dir(working_dir)
        .spawn()
        .map_err(|error| error.to_string())?;

    Ok(LaunchGameResult {
        pid: child.id(),
        exe_path: resolved.to_string_lossy().into_owned(),
        resolved_exe_path: if had_exe_path {
            None
        } else {
            Some(resolved.to_string_lossy().into_owned())
        },
    })
}

#[tauri::command]
fn is_process_running(pid: u32) -> Result<bool, String> {
    Ok(check_process_running(pid))
}

fn remove_path_inner(path: &Path) -> Result<(), String> {
    if path.is_dir() {
        fs::remove_dir_all(path).map_err(|error| error.to_string())
    } else if path.is_file() {
        fs::remove_file(path).map_err(|error| error.to_string())
    } else {
        Ok(())
    }
}

#[tauri::command]
fn remove_path(app: tauri::AppHandle, path: String) -> Result<(), String> {
    let downloads = resolve_subdir(&app, "downloads")?;
    let installs = resolve_subdir(&app, "installs")?;
    let cheats = resolve_subdir(&app, "cheats")?;
    let patches = resolve_subdir(&app, "patches")?;
    let mods = resolve_subdir(&app, "mods")?;
    remove_path_within_roots(
        Path::new(&path),
        &[&downloads, &installs, &cheats, &patches, &mods],
    )
}

/// The containment rules of `remove_path`, without the `AppHandle`. The target
/// must be strictly below one of the roots — a root directory itself is never
/// removable, so a bad path cannot take a whole app directory with it.
fn remove_path_within_roots(target: &Path, roots: &[&Path]) -> Result<(), String> {
    ensure_path_strictly_under_any_root(target, roots)?;
    if !target.exists() {
        return Ok(());
    }
    remove_path_inner(target)
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct FlipsApplyResult {
    pub output_path: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ApplyStagedModResult {
    pub applied: u32,
}

fn sanitize_mod_filename(name: &str) -> String {
    let trimmed = name.trim().replace('\\', "/");
    let base = trimmed.rsplit('/').next().unwrap_or("mod.bin");
    let cleaned: String = base
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '.' || c == '-' || c == '_' {
                c
            } else {
                '_'
            }
        })
        .collect();
    let trimmed_clean = cleaned.trim_start_matches('.');
    if trimmed_clean.is_empty() {
        "mod.bin".to_string()
    } else {
        trimmed_clean.to_string()
    }
}

fn is_mod_zip_path(path: &Path) -> bool {
    path.extension()
        .and_then(|ext| ext.to_str())
        .is_some_and(|ext| ext.eq_ignore_ascii_case("zip"))
}

/// Copy a staged mod file or extract a zip into the game install directory (path-safe).
#[tauri::command]
fn apply_staged_mod(
    app: tauri::AppHandle,
    source_path: String,
    install_root: String,
) -> Result<ApplyStagedModResult, String> {
    let mods = resolve_subdir(&app, "mods")?;
    let installs = resolve_subdir(&app, "installs")?;
    let source = PathBuf::from(&source_path);
    let destination_root = PathBuf::from(&install_root);
    ensure_path_under_root(&source, &mods)?;
    // Mods land inside one game's folder, never in the installs root itself.
    ensure_path_strictly_under_root(&destination_root, &installs)?;
    if !source.is_file() {
        return Err(format!("Staged mod not found: {source_path}"));
    }

    let mut applied: u32 = 0;
    if is_mod_zip_path(&source) {
        let file = File::open(&source).map_err(|error| error.to_string())?;
        let mut zip = ZipArchive::new(file).map_err(|error| error.to_string())?;
        for index in 0..zip.len() {
            let mut entry = zip.by_index(index).map_err(|error| error.to_string())?;
            let entry_path = match entry.enclosed_name() {
                Some(path) => destination_root.join(path),
                None => continue,
            };
            if !entry_path.starts_with(&destination_root) {
                continue;
            }
            if entry.name().ends_with('/') {
                fs::create_dir_all(&entry_path).map_err(|error| error.to_string())?;
                continue;
            }
            if let Some(parent) = entry_path.parent() {
                fs::create_dir_all(parent).map_err(|error| error.to_string())?;
            }
            let mut out = File::create(&entry_path).map_err(|error| error.to_string())?;
            copy(&mut entry, &mut out).map_err(|error| error.to_string())?;
            applied += 1;
        }
    } else {
        let file_name = source
            .file_name()
            .and_then(|n| n.to_str())
            .map(sanitize_mod_filename)
            .unwrap_or_else(|| "mod.bin".to_string());
        let target = destination_root.join(file_name);
        ensure_path_under_root(&target, &installs)?;
        if let Some(parent) = target.parent() {
            fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
        fs::copy(&source, &target).map_err(|error| error.to_string())?;
        applied = 1;
    }

    Ok(ApplyStagedModResult { applied })
}

#[tauri::command]
fn get_flips_path() -> Result<String, String> {
    Ok(std::env::var("FLIPS_PATH").unwrap_or_default())
}

/// Apply an IPS/BPS patch with Flips. Paths must live under app_data/patches.
#[tauri::command]
fn run_flips_apply(
    app: tauri::AppHandle,
    flips_path: Option<String>,
    patch_path: String,
    rom_path: String,
    output_path: Option<String>,
    game_uuid: String,
) -> Result<FlipsApplyResult, String> {
    let patches = resolve_subdir(&app, "patches")?;
    let downloads = resolve_subdir(&app, "downloads")?;
    let installs = resolve_subdir(&app, "installs")?;
    let patch = PathBuf::from(&patch_path);
    let rom = PathBuf::from(&rom_path);
    ensure_path_under_root(&patch, &patches)?;
    ensure_path_under_any_root(&rom, &[&patches, &downloads, &installs])?;
    if !patch.is_file() {
        return Err(format!("Patch not found: {patch_path}"));
    }
    if !rom.is_file() {
        return Err(format!("ROM not found: {rom_path}"));
    }

    let flips = flips_path
        .filter(|value| !value.trim().is_empty())
        .or_else(|| {
            std::env::var("FLIPS_PATH")
                .ok()
                .filter(|v| !v.trim().is_empty())
        })
        .ok_or_else(|| {
            "FLIPS_PATH not configured. Install Flips and set FLIPS_PATH, or apply manually."
                .to_string()
        })?;

    let out = if let Some(explicit) = output_path.filter(|v| !v.trim().is_empty()) {
        PathBuf::from(explicit)
    } else {
        let safe_uuid = game_uuid
            .chars()
            .map(|c| {
                if c.is_ascii_alphanumeric() || c == '-' || c == '_' {
                    c
                } else {
                    '_'
                }
            })
            .collect::<String>();
        let rom_name = rom
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("rom.bin");
        let stem = Path::new(rom_name)
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("rom");
        let ext = Path::new(rom_name)
            .extension()
            .and_then(|e| e.to_str())
            .unwrap_or("bin");
        patches
            .join(safe_uuid)
            .join(format!("{stem}.patched.{ext}"))
    };
    ensure_path_under_root(&out, &patches)?;
    if let Some(parent) = out.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }

    let patch_s = patch.to_string_lossy().into_owned();
    let rom_s = rom.to_string_lossy().into_owned();
    let out_s = out.to_string_lossy().into_owned();
    let status = std::process::Command::new(&flips)
        .args(["--apply", &patch_s, &rom_s, &out_s])
        .status()
        .map_err(|error| format!("Failed to start Flips: {error}"))?;
    if !status.success() {
        return Err(format!("Flips exited with status {status}"));
    }
    Ok(FlipsApplyResult { output_path: out_s })
}

#[tauri::command]
fn rename_path(app: tauri::AppHandle, from: String, to: String) -> Result<(), String> {
    let installs = resolve_subdir(&app, "installs")?;
    let source = PathBuf::from(&from);
    let destination = PathBuf::from(&to);
    ensure_path_strictly_under_root(&source, &installs)?;
    ensure_path_strictly_under_root(&destination, &installs)?;
    if let Some(parent) = destination.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    fs::rename(&source, &destination).map_err(|error| error.to_string())
}

/// Shown when a reveal path names a network share or a device.
const NETWORK_PATH_REFUSED: &str =
    "Network (UNC) and device paths are blocked — map the share to a drive letter and use that path instead";

fn is_absolute_os_path(path: &Path) -> bool {
    if path.is_absolute() {
        return true;
    }
    let s = path.to_string_lossy();
    // UNC / drive letter may still parse absolute on Windows; keep explicit checks.
    // "Absolute" is not "allowed": `validate_reveal_path` refuses UNC and device
    // paths (`is_network_or_device_path`) before it ever calls this.
    s.starts_with("\\\\")
        || s.starts_with("//")
        || (s.len() >= 3
            && s.as_bytes()[0].is_ascii_alphabetic()
            && s.as_bytes()[1] == b':'
            && (s.as_bytes()[2] == b'\\' || s.as_bytes()[2] == b'/'))
}

fn path_has_dotdot_segment(path: &str) -> bool {
    path.split(['/', '\\']).any(|segment| segment == "..")
}

/// Is this a UNC share or a Win32/NT device path?
///
/// Covers `\\host\share` and `//host/share` (and the mixed `\/` / `/\` forms
/// Windows treats the same), the device namespaces `\\?\…` and `\\.\…`, and the
/// NT object prefix `\??\…` (std reads it like the verbatim `\\?\` prefix).
///
/// On Windows merely probing such a path — `Path::exists()` is enough — makes the
/// OS open an SMB connection and answer the server's NTLM challenge, handing the
/// user's credential hash to whichever host the path names. A queued `open_path`
/// is written by the server, which the companion must not trust that far, so
/// these are refused on the raw string before any filesystem call, on every
/// platform.
fn is_network_or_device_path(path: &str) -> bool {
    let is_separator = |c: char| c == '/' || c == '\\';
    let mut chars = path.chars();
    if let (Some(first), Some(second)) = (chars.next(), chars.next()) {
        if is_separator(first) && is_separator(second) {
            return true;
        }
    }
    path.starts_with("\\??\\") || path.starts_with("/??/")
}

/// Validate a caller-supplied reveal path and classify it as a file or directory.
///
/// Every rejection here happens before any OS process is spawned, which is what
/// makes the guard testable in isolation: empty / whitespace-only, longer than
/// 4096 bytes, embedded NUL / CR / LF, a UNC or device path, any `..` path
/// segment, a non-absolute path, or a path that does not exist on this machine.
/// The UNC / device check comes before the first filesystem call (`exists()`).
fn validate_reveal_path(path: &str) -> Result<(PathBuf, &'static str), String> {
    let trimmed = path.trim();
    if trimmed.is_empty() {
        return Err("Path is required".into());
    }
    if trimmed.len() > 4096 {
        return Err("Path is too long".into());
    }
    if trimmed.contains('\0') || trimmed.contains('\n') || trimmed.contains('\r') {
        return Err("Path contains invalid control characters".into());
    }
    if is_network_or_device_path(trimmed) {
        return Err(NETWORK_PATH_REFUSED.into());
    }
    if path_has_dotdot_segment(trimmed) {
        return Err("Path must not contain .. segments".into());
    }

    let target = PathBuf::from(trimmed);
    if !is_absolute_os_path(&target) {
        return Err("Path must be absolute".into());
    }
    if !target.exists() {
        return Err(format!("Path does not exist on this machine: {trimmed}"));
    }

    let revealed_as = if target.is_file() {
        "file"
    } else {
        "directory"
    };
    Ok((target, revealed_as))
}

/// Open `path` in Explorer (Windows), Finder (macOS), or the default file manager (Linux).
/// When `select` is true and the path is a file, select it in the parent folder.
#[tauri::command]
fn reveal_path_in_os(path: String, select: Option<bool>) -> Result<RevealPathResult, String> {
    let trimmed = path.trim();
    let (target, revealed_as) = validate_reveal_path(trimmed)?;
    let select_item = select.unwrap_or(true);

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        let status = if select_item && target.is_file() {
            // explorer /select,<path> — comma is part of the switch, not a shell.
            std::process::Command::new("explorer")
                .arg(format!("/select,{}", target.display()))
                .creation_flags(CREATE_NO_WINDOW)
                .status()
                .map_err(|error| format!("Failed to start Explorer: {error}"))?
        } else {
            let folder = if target.is_file() {
                target
                    .parent()
                    .map(Path::to_path_buf)
                    .unwrap_or_else(|| target.clone())
            } else {
                target.clone()
            };
            std::process::Command::new("explorer")
                .arg(folder.as_os_str())
                .creation_flags(CREATE_NO_WINDOW)
                .status()
                .map_err(|error| format!("Failed to start Explorer: {error}"))?
        };
        // explorer.exe often returns non-zero even on success; existence check is enough.
        let _ = status;
    }

    #[cfg(target_os = "macos")]
    {
        let status = if select_item {
            std::process::Command::new("open")
                .args(["-R", trimmed])
                .status()
                .map_err(|error| format!("Failed to start Finder: {error}"))?
        } else {
            let open_target = if target.is_file() {
                target
                    .parent()
                    .map(|p| p.to_string_lossy().into_owned())
                    .unwrap_or_else(|| trimmed.to_string())
            } else {
                trimmed.to_string()
            };
            std::process::Command::new("open")
                .arg(&open_target)
                .status()
                .map_err(|error| format!("Failed to start Finder: {error}"))?
        };
        if !status.success() {
            return Err(format!("open exited with status {status}"));
        }
    }

    #[cfg(all(unix, not(target_os = "macos")))]
    {
        let open_target = if target.is_file() {
            target
                .parent()
                .map(|p| p.to_string_lossy().into_owned())
                .unwrap_or_else(|| trimmed.to_string())
        } else {
            trimmed.to_string()
        };
        let status = std::process::Command::new("xdg-open")
            .arg(&open_target)
            .status()
            .map_err(|error| format!("Failed to start file manager: {error}"))?;
        if !status.success() {
            return Err(format!("xdg-open exited with status {status}"));
        }
        let _ = select_item;
    }

    #[cfg(not(any(windows, unix)))]
    {
        let _ = (select_item, revealed_as);
        return Err("Reveal path is not supported on this OS".into());
    }

    Ok(RevealPathResult {
        path: trimmed.to_string(),
        revealed_as: revealed_as.to_string(),
    })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            load_config,
            save_config,
            secure_store_get,
            secure_store_set,
            secure_store_delete,
            load_lifecycle_registry,
            save_lifecycle_registry,
            load_installs,
            save_installs,
            retain_install_files,
            preserve_install_files,
            restore_install_snapshot,
            get_app_subdir,
            write_file_bytes,
            append_file_bytes,
            extract_zip_archive,
            launch_game,
            reveal_path_in_os,
            is_process_running,
            remove_path,
            rename_path,
            get_flips_path,
            run_flips_apply,
            apply_staged_mod,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
    // `super::*` also re-globs lib.rs's `use std::io::{copy, Write}`, so the
    // `Write` trait `write_zip` needs is already in scope here.
    use super::*;
    use std::fs;
    use tempfile::tempdir;
    use zip::write::{SimpleFileOptions, ZipWriter};

    // ---------------------------------------------------------------
    // ensure_path_under_root
    // ---------------------------------------------------------------

    #[test]
    fn under_root_accepts_file_directly_inside() {
        let root = tempdir().unwrap();
        let target = root.path().join("archive.zip");
        assert!(ensure_path_under_root(&target, root.path()).is_ok());
    }

    #[test]
    fn under_root_accepts_existing_nested_file() {
        let root = tempdir().unwrap();
        let nested = root.path().join("a/b/c");
        fs::create_dir_all(&nested).unwrap();
        let target = nested.join("game.exe");
        fs::write(&target, b"x").unwrap();
        assert!(ensure_path_under_root(&target, root.path()).is_ok());
    }

    #[test]
    fn under_root_rejects_sibling_directory() {
        let base = tempdir().unwrap();
        let root = base.path().join("installs");
        let outside = base.path().join("outside");
        fs::create_dir_all(&root).unwrap();
        fs::create_dir_all(&outside).unwrap();
        let target = outside.join("evil.exe");
        let err = ensure_path_under_root(&target, &root).unwrap_err();
        assert!(err.contains("outside allowed"), "got: {err}");
    }

    #[test]
    fn under_root_rejects_dotdot_traversal_out_of_root() {
        let base = tempdir().unwrap();
        let root = base.path().join("installs");
        let child = root.join("game");
        fs::create_dir_all(&child).unwrap();
        // installs/game/../../escape.txt resolves to base/escape.txt
        let target = child.join("..").join("..").join("escape.txt");
        let err = ensure_path_under_root(&target, &root).unwrap_err();
        assert!(err.contains("outside allowed"), "got: {err}");
    }

    #[test]
    fn under_root_rejects_absolute_path_elsewhere() {
        let base = tempdir().unwrap();
        let root = base.path().join("installs");
        fs::create_dir_all(&root).unwrap();
        let other = tempdir().unwrap();
        let target = other.path().join("payload.bin");
        fs::write(&target, b"x").unwrap();
        assert!(ensure_path_under_root(&target, &root).is_err());
    }

    #[test]
    fn under_root_errors_when_root_missing() {
        let base = tempdir().unwrap();
        let missing_root = base.path().join("nope");
        let target = base.path().join("nope/x.txt");
        assert!(ensure_path_under_root(&target, &missing_root).is_err());
    }

    // ---------------------------------------------------------------
    // ensure_path_under_any_root
    // ---------------------------------------------------------------

    #[test]
    fn any_root_accepts_when_under_a_later_root() {
        let base = tempdir().unwrap();
        let downloads = base.path().join("downloads");
        let mods = base.path().join("mods");
        fs::create_dir_all(&downloads).unwrap();
        fs::create_dir_all(&mods).unwrap();
        let target = mods.join("patch.bin");
        assert!(
            ensure_path_under_any_root(&target, &[downloads.as_path(), mods.as_path()]).is_ok()
        );
    }

    #[test]
    fn any_root_rejects_when_under_none_of_them() {
        let base = tempdir().unwrap();
        let downloads = base.path().join("downloads");
        let mods = base.path().join("mods");
        let elsewhere = base.path().join("elsewhere");
        for dir in [&downloads, &mods, &elsewhere] {
            fs::create_dir_all(dir).unwrap();
        }
        let target = elsewhere.join("x.bin");
        let err = ensure_path_under_any_root(&target, &[downloads.as_path(), mods.as_path()])
            .unwrap_err();
        assert!(err.contains("outside allowed"), "got: {err}");
    }

    #[test]
    fn any_root_rejects_dotdot_bridge_between_roots() {
        let base = tempdir().unwrap();
        let downloads = base.path().join("downloads");
        let mods = base.path().join("mods");
        fs::create_dir_all(&downloads).unwrap();
        fs::create_dir_all(&mods).unwrap();
        // Start inside `mods`, climb out, land in `downloads` — still "allowed"
        // overall, but proves traversal is resolved rather than string-matched.
        let bridged = mods.join("..").join("downloads").join("real.bin");
        assert!(
            ensure_path_under_any_root(&bridged, &[downloads.as_path(), mods.as_path()]).is_ok()
        );
        // ...and the same climb into a non-root sibling is refused.
        let sibling = base.path().join("sibling");
        fs::create_dir_all(&sibling).unwrap();
        let escaped = mods.join("..").join("sibling").join("real.bin");
        assert!(
            ensure_path_under_any_root(&escaped, &[downloads.as_path(), mods.as_path()]).is_err()
        );
    }

    // ---------------------------------------------------------------
    // path_has_dotdot_segment / is_absolute_os_path
    // ---------------------------------------------------------------

    #[test]
    fn dotdot_segment_detection() {
        assert!(path_has_dotdot_segment("/home/user/../etc/passwd"));
        assert!(path_has_dotdot_segment("C:\\Users\\me\\..\\Administrator"));
        assert!(path_has_dotdot_segment(".."));
        assert!(path_has_dotdot_segment("a/../b"));
        assert!(!path_has_dotdot_segment("/home/user/games/rom.bin"));
        assert!(!path_has_dotdot_segment("/home/user/..name/ok")); // ".." only as a full segment
        assert!(!path_has_dotdot_segment("C:\\Users\\me\\game..v2"));
    }

    #[test]
    fn absolute_path_detection() {
        assert!(is_absolute_os_path(Path::new("C:\\Users\\me\\game")));
        assert!(is_absolute_os_path(Path::new("C:/Users/me/game")));
        assert!(is_absolute_os_path(Path::new("\\\\server\\share\\game")));
        assert!(is_absolute_os_path(Path::new("//server/share/game")));
        assert!(!is_absolute_os_path(Path::new("relative/path")));
        assert!(!is_absolute_os_path(Path::new("game.exe")));
        assert!(!is_absolute_os_path(Path::new("C:game"))); // drive-relative, no separator
    }

    // ---------------------------------------------------------------
    // validate_reveal_path (reveal_path_in_os guards)
    // ---------------------------------------------------------------

    #[test]
    fn reveal_rejects_empty_or_whitespace() {
        assert_eq!(validate_reveal_path("").unwrap_err(), "Path is required");
        assert_eq!(
            validate_reveal_path("    ").unwrap_err(),
            "Path is required"
        );
    }

    #[test]
    fn reveal_rejects_overlong_path() {
        let long = format!("/{}", "a".repeat(5000));
        assert_eq!(validate_reveal_path(&long).unwrap_err(), "Path is too long");
    }

    #[test]
    fn reveal_rejects_control_characters() {
        assert!(validate_reveal_path("/tmp/a\nb")
            .unwrap_err()
            .contains("control"));
        assert!(validate_reveal_path("/tmp/a\rb")
            .unwrap_err()
            .contains("control"));
        assert!(validate_reveal_path("/tmp/a\0b")
            .unwrap_err()
            .contains("control"));
    }

    #[test]
    fn reveal_rejects_dotdot_segments() {
        assert!(validate_reveal_path("/home/user/../root/secret")
            .unwrap_err()
            .contains(".."));
        assert!(validate_reveal_path("C:\\Users\\me\\..\\Administrator\\x")
            .unwrap_err()
            .contains(".."));
    }

    #[test]
    fn reveal_rejects_non_absolute_path() {
        assert_eq!(
            validate_reveal_path("relative/dir/here").unwrap_err(),
            "Path must be absolute"
        );
    }

    #[test]
    fn reveal_rejects_absolute_but_missing_path() {
        let base = tempdir().unwrap();
        let missing = base.path().join("does-not-exist-42");
        let err = validate_reveal_path(missing.to_str().unwrap()).unwrap_err();
        assert!(err.contains("does not exist"), "got: {err}");
    }

    #[test]
    fn reveal_accepts_existing_directory() {
        let base = tempdir().unwrap();
        let (path, kind) = validate_reveal_path(base.path().to_str().unwrap()).unwrap();
        assert_eq!(kind, "directory");
        assert_eq!(path, base.path());
    }

    #[test]
    fn reveal_accepts_existing_file() {
        let base = tempdir().unwrap();
        let file = base.path().join("readme.txt");
        fs::write(&file, b"hi").unwrap();
        let (_path, kind) = validate_reveal_path(file.to_str().unwrap()).unwrap();
        assert_eq!(kind, "file");
    }

    // ---------------------------------------------------------------
    // extract_zip_to_dir — enclosed_name() / zip-slip handling
    // ---------------------------------------------------------------

    fn write_zip(path: &Path, entries: &[(&str, &[u8])]) {
        let file = fs::File::create(path).unwrap();
        let mut zip = ZipWriter::new(file);
        let opts = SimpleFileOptions::default();
        for (name, body) in entries {
            if name.ends_with('/') {
                zip.add_directory(name.trim_end_matches('/'), opts).unwrap();
            } else {
                zip.start_file(*name, opts).unwrap();
                zip.write_all(body).unwrap();
            }
        }
        zip.finish().unwrap();
    }

    #[test]
    fn extract_places_normal_entries_under_destination() {
        let work = tempdir().unwrap();
        let archive = work.path().join("bundle.zip");
        write_zip(
            &archive,
            &[
                ("game/", b""),
                ("game/data.bin", b"payload"),
                ("readme.txt", b"hi"),
            ],
        );
        let dest = work.path().join("out");
        let result = extract_zip_to_dir(&archive, &dest).unwrap();
        assert_eq!(result.extract_path, dest.to_string_lossy().into_owned());
        assert!(dest.join("game/data.bin").is_file());
        assert_eq!(fs::read(dest.join("game/data.bin")).unwrap(), b"payload");
        assert!(dest.join("readme.txt").is_file());
    }

    #[test]
    fn extract_drops_parent_traversal_entry() {
        let work = tempdir().unwrap();
        let archive = work.path().join("evil.zip");
        write_zip(
            &archive,
            &[("../escape.txt", b"pwned"), ("safe.txt", b"ok")],
        );
        let dest = work.path().join("out");
        extract_zip_to_dir(&archive, &dest).unwrap();

        // The traversal entry must not have been written anywhere outside dest.
        assert!(!work.path().join("escape.txt").exists());
        assert!(!dest.parent().unwrap().join("escape.txt").exists());
        // The legitimate entry still lands.
        assert!(dest.join("safe.txt").is_file());
        // And nothing escaped the destination at all.
        assert!(!dest.join("../escape.txt").exists());
    }

    #[test]
    fn extract_drops_deep_traversal_and_absolute_entries() {
        let work = tempdir().unwrap();
        let src = work.path().join("src");
        fs::create_dir_all(&src).unwrap();
        let archive = src.join("evil2.zip");
        write_zip(
            &archive,
            &[
                ("a/b/../../../../../../tmp/evil.bin", b"x"),
                ("nested/ok.bin", b"y"),
            ],
        );
        let dest = work.path().join("out");
        extract_zip_to_dir(&archive, &dest).unwrap();

        assert!(dest.join("nested/ok.bin").is_file());
        // Nothing may have been written outside the destination.
        assert!(!work.path().join("tmp").exists());
        assert!(!work.path().join("evil.bin").exists());
        assert!(!dest.parent().unwrap().join("tmp/evil.bin").exists());

        // Walk the destination tree; every extracted path must stay inside it.
        let mut stack = vec![dest.clone()];
        while let Some(dir) = stack.pop() {
            for entry in fs::read_dir(&dir).unwrap() {
                let path = entry.unwrap().path();
                assert!(path.starts_with(&dest), "escaped path: {}", path.display());
                if path.is_dir() {
                    stack.push(path);
                }
            }
        }
    }

    #[test]
    fn extract_errors_when_archive_missing() {
        let work = tempdir().unwrap();
        let archive = work.path().join("absent.zip");
        let dest = work.path().join("out");
        let err = extract_zip_to_dir(&archive, &dest).unwrap_err();
        assert!(err.contains("Archive not found"), "got: {err}");
    }

    #[test]
    fn extract_replaces_a_pre_existing_destination() {
        let work = tempdir().unwrap();
        let archive = work.path().join("bundle.zip");
        write_zip(&archive, &[("fresh.txt", b"new")]);
        let dest = work.path().join("out");
        fs::create_dir_all(&dest).unwrap();
        fs::write(dest.join("stale.txt"), b"old").unwrap();

        extract_zip_to_dir(&archive, &dest).unwrap();
        assert!(dest.join("fresh.txt").is_file());
        assert!(!dest.join("stale.txt").exists());
    }

    // ---------------------------------------------------------------
    // strictly-under-root — destructive operations never take a root
    // ---------------------------------------------------------------

    #[test]
    fn plain_check_accepts_the_root_itself_but_strict_does_not() {
        let root = tempdir().unwrap();
        assert!(ensure_path_under_root(root.path(), root.path()).is_ok());
        let err = ensure_path_strictly_under_root(root.path(), root.path()).unwrap_err();
        assert!(err.contains("not the directory itself"), "got: {err}");
    }

    #[test]
    fn strict_rejects_dot_segment_and_dotdot_that_resolve_to_the_root() {
        let root = tempdir().unwrap();
        // A game id of "." joins to `installs/.` — the root under another name.
        assert!(ensure_path_strictly_under_root(&root.path().join("."), root.path()).is_err());
        // installs/sub/.. also lands on the root.
        let sub = root.path().join("sub");
        fs::create_dir_all(&sub).unwrap();
        assert!(ensure_path_strictly_under_root(&sub.join(".."), root.path()).is_err());
    }

    #[test]
    fn strict_accepts_children_existing_or_not() {
        let root = tempdir().unwrap();
        let existing = root.path().join("game");
        fs::create_dir_all(&existing).unwrap();
        assert!(ensure_path_strictly_under_root(&existing, root.path()).is_ok());
        assert!(ensure_path_strictly_under_root(&root.path().join("missing"), root.path()).is_ok());
    }

    #[test]
    fn strict_still_rejects_paths_outside_the_root() {
        let base = tempdir().unwrap();
        let root = base.path().join("installs");
        let outside = base.path().join("outside");
        fs::create_dir_all(&root).unwrap();
        fs::create_dir_all(&outside).unwrap();
        let err = ensure_path_strictly_under_root(&outside.join("x"), &root).unwrap_err();
        assert!(err.contains("outside allowed"), "got: {err}");
        // The parent of the root (game id "..") is outside too.
        assert!(ensure_path_strictly_under_root(&root.join(".."), &root).is_err());
    }

    #[test]
    fn strict_any_root_rejects_every_root_but_accepts_their_children() {
        let base = tempdir().unwrap();
        let downloads = base.path().join("downloads");
        let installs = base.path().join("installs");
        fs::create_dir_all(&downloads).unwrap();
        fs::create_dir_all(&installs).unwrap();
        let roots = [downloads.as_path(), installs.as_path()];
        assert!(ensure_path_strictly_under_any_root(&downloads, &roots).is_err());
        assert!(ensure_path_strictly_under_any_root(&installs, &roots).is_err());
        assert!(ensure_path_strictly_under_any_root(&installs.join("game"), &roots).is_ok());
        assert!(ensure_path_strictly_under_any_root(&downloads.join("g.zip"), &roots).is_ok());
    }

    // ---------------------------------------------------------------
    // extract_zip_within_roots — a bad game id must not wipe the installs root
    // ---------------------------------------------------------------

    struct AppDirs {
        _base: tempfile::TempDir,
        downloads: PathBuf,
        installs: PathBuf,
    }

    fn app_dirs() -> AppDirs {
        let base = tempdir().unwrap();
        let downloads = base.path().join("downloads");
        let installs = base.path().join("installs");
        fs::create_dir_all(&downloads).unwrap();
        fs::create_dir_all(&installs).unwrap();
        AppDirs {
            _base: base,
            downloads,
            installs,
        }
    }

    #[test]
    fn extract_refuses_to_wipe_the_installs_root() {
        let dirs = app_dirs();
        let archive = dirs.downloads.join("bundle.zip");
        write_zip(&archive, &[("fresh.txt", b"new")]);
        let other_game = dirs.installs.join("other-game");
        fs::create_dir_all(&other_game).unwrap();
        fs::write(other_game.join("save.dat"), b"precious").unwrap();

        // The root itself, and `installs/.` — what a game id of "." produces.
        for destination in [dirs.installs.clone(), dirs.installs.join(".")] {
            let err =
                extract_zip_within_roots(&archive, &destination, &dirs.downloads, &dirs.installs)
                    .unwrap_err();
            assert!(err.contains("not the directory itself"), "got: {err}");
            assert_eq!(fs::read(other_game.join("save.dat")).unwrap(), b"precious");
            assert!(!dirs.installs.join("fresh.txt").exists());
        }
    }

    #[test]
    fn extract_within_roots_still_installs_below_the_root() {
        let dirs = app_dirs();
        let archive = dirs.downloads.join("bundle.zip");
        write_zip(&archive, &[("fresh.txt", b"new")]);
        let destination = dirs.installs.join("game-1");
        fs::create_dir_all(&destination).unwrap();
        fs::write(destination.join("stale.txt"), b"old").unwrap();

        extract_zip_within_roots(&archive, &destination, &dirs.downloads, &dirs.installs).unwrap();
        assert!(destination.join("fresh.txt").is_file());
        assert!(!destination.join("stale.txt").exists());
    }

    #[test]
    fn extract_within_roots_rejects_a_destination_outside_installs() {
        let dirs = app_dirs();
        let archive = dirs.downloads.join("bundle.zip");
        write_zip(&archive, &[("fresh.txt", b"new")]);
        // Game id ".." would target the app-data directory itself.
        let err = extract_zip_within_roots(
            &archive,
            &dirs.installs.join(".."),
            &dirs.downloads,
            &dirs.installs,
        )
        .unwrap_err();
        assert!(err.contains("outside allowed"), "got: {err}");
    }

    // ---------------------------------------------------------------
    // remove_path_within_roots — uninstall never removes a root directory
    // ---------------------------------------------------------------

    #[test]
    fn remove_refuses_a_root_directory_and_keeps_its_contents() {
        let dirs = app_dirs();
        let game = dirs.installs.join("game-1");
        fs::create_dir_all(&game).unwrap();
        fs::write(game.join("save.dat"), b"precious").unwrap();
        let roots = [dirs.downloads.as_path(), dirs.installs.as_path()];

        for target in [
            dirs.installs.clone(),
            dirs.installs.join("."),
            dirs.downloads.clone(),
        ] {
            assert!(
                remove_path_within_roots(&target, &roots).is_err(),
                "removed {}",
                target.display()
            );
        }
        assert_eq!(fs::read(game.join("save.dat")).unwrap(), b"precious");
        assert!(dirs.downloads.is_dir());
    }

    #[test]
    fn remove_deletes_a_game_directory_and_an_archive_below_a_root() {
        let dirs = app_dirs();
        let game = dirs.installs.join("game-1");
        fs::create_dir_all(game.join("data")).unwrap();
        fs::write(game.join("data/x.bin"), b"x").unwrap();
        let archive = dirs.downloads.join("game-1.zip");
        fs::write(&archive, b"zip").unwrap();
        let roots = [dirs.downloads.as_path(), dirs.installs.as_path()];

        remove_path_within_roots(&game, &roots).unwrap();
        remove_path_within_roots(&archive, &roots).unwrap();
        assert!(!game.exists());
        assert!(!archive.exists());
        assert!(dirs.installs.is_dir());
        assert!(dirs.downloads.is_dir());
    }

    #[test]
    fn remove_of_a_missing_child_is_a_no_op() {
        let dirs = app_dirs();
        let roots = [dirs.installs.as_path()];
        assert!(remove_path_within_roots(&dirs.installs.join("gone"), &roots).is_ok());
    }

    #[test]
    fn remove_rejects_paths_outside_every_root() {
        let dirs = app_dirs();
        let outside = tempdir().unwrap();
        let victim = outside.path().join("keep.txt");
        fs::write(&victim, b"x").unwrap();
        let roots = [dirs.downloads.as_path(), dirs.installs.as_path()];
        assert!(remove_path_within_roots(&victim, &roots).is_err());
        assert!(victim.is_file());
    }

    // ---------------------------------------------------------------
    // UNC / device paths — refused before any filesystem probe
    // ---------------------------------------------------------------

    #[test]
    fn network_or_device_path_detection() {
        for path in [
            r"\\attacker\share",
            r"\\attacker\share\game",
            "//attacker/share",
            r"\/attacker\share",
            r"/\attacker/share",
            r"\\?\C:\Windows",
            r"\\?\UNC\attacker\share",
            r"\\.\pipe\name",
            "//?/C:/Windows",
            r"\??\C:\Windows",
            "/??/C:/Windows",
        ] {
            assert!(is_network_or_device_path(path), "missed: {path}");
        }
        for path in [
            "",
            "/",
            "/mnt/user/games",
            "/home/me/games",
            r"C:\Users\me\game",
            "C:/Users/me/game",
            r"\single\leading\backslash",
            "relative/path",
            "/a//b",
            r"D:\\double\inside",
        ] {
            assert!(!is_network_or_device_path(path), "false positive: {path}");
        }
    }

    #[test]
    fn reveal_rejects_unc_and_device_paths_before_any_filesystem_probe() {
        // Every one of these would otherwise fall through to `target.exists()`
        // (and, on Windows, to an SMB connection). The refusal message — not
        // "does not exist" — proves the check runs first.
        for path in [
            r"\\attacker\x",
            "//attacker/x",
            r"\\attacker\share\dir\file.txt",
            r"\/attacker\x",
            r"\\?\C:\Windows",
            r"\\?\UNC\attacker\x",
            r"\\.\pipe\x",
            r"\??\C:\Windows",
        ] {
            assert_eq!(
                validate_reveal_path(path).unwrap_err(),
                NETWORK_PATH_REFUSED,
                "path: {path}"
            );
            // Surrounding whitespace does not hide it (the command trims first,
            // but the validator must not depend on that).
            assert_eq!(
                validate_reveal_path(&format!("  {path}  ")).unwrap_err(),
                NETWORK_PATH_REFUSED,
                "padded path: {path}"
            );
        }
    }

    #[test]
    fn reveal_still_accepts_a_local_absolute_path() {
        let base = tempdir().unwrap();
        assert!(validate_reveal_path(base.path().to_str().unwrap()).is_ok());
    }

    // ---------------------------------------------------------------
    // user_facing_path — no \\?\ in the install record
    // ---------------------------------------------------------------

    #[test]
    fn user_facing_path_strips_only_the_verbatim_drive_prefix() {
        assert_eq!(
            user_facing_path(r"\\?\C:\Users\me\installs\game"),
            r"C:\Users\me\installs\game"
        );
        assert_eq!(user_facing_path(r"C:\Users\me\game"), r"C:\Users\me\game");
        assert_eq!(user_facing_path("/home/me/game"), "/home/me/game");
        // Verbatim UNC and device shapes are left alone (and refused at reveal).
        assert_eq!(
            user_facing_path(r"\\?\UNC\host\share"),
            r"\\?\UNC\host\share"
        );
        assert_eq!(user_facing_path(r"\\?\pipe"), r"\\?\pipe");
    }

    // ---------------------------------------------------------------
    // validate_server_base_url — http:// only on the local network
    // ---------------------------------------------------------------

    #[test]
    fn server_url_accepts_https_anywhere_and_blank() {
        for url in [
            "https://games.example.com",
            "https://games.example.com:8443/prefix/",
            "https://8.8.8.8",
            "HTTPS://Games.Example.Com",
            "",
            "   ",
        ] {
            assert!(validate_server_base_url(url).is_ok(), "rejected: {url:?}");
        }
    }

    #[test]
    fn server_url_accepts_http_for_loopback_and_private_hosts() {
        for url in [
            "http://localhost:5000",
            "http://127.0.0.1:5000",
            "http://127.255.0.3",
            "http://[::1]:5000",
            "http://10.1.2.3",
            "http://172.16.0.1",
            "http://172.31.255.254",
            "http://192.168.1.50:8080",
            "http://169.254.10.10",
            "http://[fd12:3456:789a::1]",
            "http://[fc00::1]",
            "http://[fe80::1]",
            "http://[::ffff:192.168.1.5]",
            "http://nas.local",
            "http://NAS.LOCAL:8080/app",
            "http://nas.local./",
            "http://nas",
            "http://nas:5000",
            // WHATWG host parsing folds these to 127.0.0.1 / 192.168.0.1.
            "http://0x7f.1/",
            "http://2130706433/",
            "http://0300.0250.0.1/",
            // The host is 192.168.1.1; `evil.com` is only userinfo.
            "http://evil.com@192.168.1.1/",
        ] {
            assert!(validate_server_base_url(url).is_ok(), "rejected: {url}");
        }
    }

    #[test]
    fn server_url_refuses_http_for_public_hosts() {
        for url in [
            "http://games.example.com",
            "http://games.example.com:5000/app",
            "http://8.8.8.8",
            "http://172.15.0.1",
            "http://172.32.0.1",
            "http://192.169.1.1",
            "http://11.0.0.1",
            "http://0.0.0.0",
            "http://100.64.0.1",
            "http://[2001:db8::1]",
            "http://[::ffff:8.8.8.8]",
            "http://[fec0::1]",
            // Looks local, is a public name.
            "http://192.168.1.1.evil.com",
            "http://10.0.0.1.nip.io",
            "http://localhost.evil.com",
            "http://nas.local.evil.com",
            "http://.local",
            // Hex-encoded public address.
            "http://0x08080808/",
            // The host is evil.com; 192.168.1.1 is only userinfo.
            "http://192.168.1.1@evil.com/",
        ] {
            let err = validate_server_base_url(url).unwrap_err();
            assert!(err.contains("https://"), "no https hint for {url}: {err}");
        }
    }

    #[test]
    fn server_url_refuses_other_schemes_and_junk() {
        for url in [
            "ftp://games.example.com",
            "file:///etc/passwd",
            "ws://localhost:5000",
            "javascript:alert(1)",
            "games.example.com",
            "localhost:5000",
            "https://",
            "//games.example.com",
        ] {
            assert!(validate_server_base_url(url).is_err(), "accepted: {url}");
        }
    }

    #[test]
    fn save_config_keeps_an_already_saved_url_but_refuses_a_new_insecure_one() {
        let dir = tempdir().unwrap();
        let config = dir.path().join("config.json");
        // Nothing saved yet: a new public http URL is refused, https is fine.
        assert!(validate_config_base_url(&config, "http://games.example.com").is_err());
        assert!(validate_config_base_url(&config, "https://games.example.com").is_ok());
        assert!(validate_config_base_url(&config, "").is_ok());

        // A legacy config on disk (saved by an older build, token still inside).
        fs::write(
            &config,
            r#"{"base_url":"http://games.example.com","token":"gt_ab_secret"}"#,
        )
        .unwrap();
        // Re-saving it unchanged must work — that is the plaintext-token scrub.
        assert!(validate_config_base_url(&config, "http://games.example.com").is_ok());
        assert!(validate_config_base_url(&config, " http://games.example.com ").is_ok());
        // A different insecure URL is still refused; so is an unreadable config.
        assert!(validate_config_base_url(&config, "http://other.example.com").is_err());
        fs::write(&config, "not json").unwrap();
        assert!(validate_config_base_url(&config, "http://games.example.com").is_err());
    }
}
