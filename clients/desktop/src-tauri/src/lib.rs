use fs2::{available_space, FileExt};
use keyring::Entry;
use serde::{Deserialize, Serialize};
#[cfg(test)]
use std::cell::Cell;
use std::collections::HashMap;
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::net::{Ipv4Addr, Ipv6Addr};
use std::path::{Path, PathBuf};
use std::process::Child;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use tauri::{Emitter, Manager, State};
use url::{Host, Url};
use zip::ZipArchive;
mod install_recovery;
mod trusted_shares;

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

/// The generation an update replaced, kept for one more update so a file the new
/// archive overwrote stays recoverable (see `GameInstallRecord.superseded`).
#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct SupersededInstall {
    pub archive_path: String,
    pub extract_path: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub retained_path: Option<String>,
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
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub superseded: Option<SupersededInstall>,
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

#[derive(Debug, Clone, Serialize)]
struct GameArchiveProgress {
    operation_id: String,
    bytes_extracted: u64,
    total_bytes: u64,
}

struct GameArchiveInstallOperations(Arc<Mutex<HashMap<String, Arc<AtomicBool>>>>);

impl Default for GameArchiveInstallOperations {
    fn default() -> Self {
        Self(Arc::new(Mutex::new(HashMap::new())))
    }
}

struct GameArchiveOperationCleanup {
    operations: Arc<Mutex<HashMap<String, Arc<AtomicBool>>>>,
    operation_id: String,
}

impl Drop for GameArchiveOperationCleanup {
    fn drop(&mut self) {
        if let Ok(mut operations) = self.operations.lock() {
            operations.remove(&self.operation_id);
        }
    }
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct LaunchGameResult {
    pub pid: u32,
    pub exe_path: String,
    pub resolved_exe_path: Option<String>,
}

#[derive(Clone, Default)]
struct ManagedProcessRegistry(Arc<Mutex<HashMap<u32, bool>>>);

impl ManagedProcessRegistry {
    fn track(&self, mut child: Child) -> Result<u32, String> {
        let pid = child.id();
        self.0
            .lock()
            .map_err(|_| "Process registry is unavailable".to_string())?
            .insert(pid, true);

        let registry = Arc::clone(&self.0);
        thread::spawn(move || {
            // Waiting here reaps the direct child even when the webview is not
            // polling. Its exited state is kept for the next watcher query.
            let _ = child.wait();
            if let Ok(mut processes) = registry.lock() {
                processes.insert(pid, false);
            }
        });
        Ok(pid)
    }

    fn is_running(&self, pid: u32) -> Result<Option<bool>, String> {
        let mut processes = self
            .0
            .lock()
            .map_err(|_| "Process registry is unavailable".to_string())?;
        let state = processes.get(&pid).copied();
        if state == Some(false) {
            processes.remove(&pid);
        }
        Ok(state)
    }
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

fn validate_app_subdir(subdir: &str) -> Result<(), String> {
    const ALLOWED: &[&str] = &["downloads", "installs", "mods", "patches", "cheats"];
    if ALLOWED.contains(&subdir) {
        Ok(())
    } else {
        Err("Unsupported application directory".into())
    }
}

fn installs_root(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    resolve_subdir(app, "installs")
}

/// Said when a containment helper is handed a path it must not even look at.
const PATH_NOT_PROBEABLE: &str = "Path must be an absolute local path inside an app directory";

/// The text-only half of containment: may `path` be touched on disk at all?
///
/// `canonicalize_path`, and every `ensure_path_*` built on it, starts with
/// `path.exists()`. On Windows that probe of a UNC path opens an SMB connection
/// and answers the named host's NTLM challenge, handing it the user's credential
/// hash (the leak `is_network_or_device_path` keeps out of `open_path`). The
/// strings that reach these helpers come from the webview and from
/// `installs.json`, so they are screened as text first: UNC and device paths and
/// non-absolute ones (which would resolve against the working directory) are
/// refused before any filesystem call.
///
/// One exception, string-compared only: a Windows profile redirected to a file
/// server puts the app's own folders on a UNC path, so a UNC path at or below the
/// `root` the app itself supplied is the app's own folder, not a stranger's host.
/// A `..` segment takes a path out of that prefix (see `is_under_trusted_share`).
fn check_path_text_before_probe(path: &Path, root: &Path) -> Result<(), String> {
    let text = path.to_string_lossy();
    if is_network_or_device_path(&text) {
        let root_text = root.to_string_lossy();
        if trusted_shares::is_under_trusted_share(&text, &[&*root_text]) {
            return Ok(());
        }
        return Err(PATH_NOT_PROBEABLE.into());
    }
    if !path.is_absolute() {
        return Err(PATH_NOT_PROBEABLE.into());
    }
    Ok(())
}

fn canonicalize_path(path: &Path, root: &Path) -> Result<PathBuf, String> {
    check_path_text_before_probe(path, root)?;
    if path.exists() {
        return path.canonicalize().map_err(|error| error.to_string());
    }

    // Staging paths commonly have multiple missing levels (for example,
    // patches/<game>/<file>). Canonicalize the closest existing ancestor so
    // existing symlinks/reparse points are resolved, then append the missing
    // components for the containment check before the caller creates them.
    let mut missing = Vec::new();
    let mut ancestor = path;
    while !ancestor.exists() {
        let Some(name) = ancestor.file_name() else {
            return Ok(path.to_path_buf());
        };
        missing.push(name.to_os_string());
        let Some(parent) = ancestor.parent() else {
            return Ok(path.to_path_buf());
        };
        ancestor = parent;
    }

    let mut canonical = ancestor.canonicalize().map_err(|error| error.to_string())?;
    for component in missing.into_iter().rev() {
        canonical.push(component);
    }
    Ok(canonical)
}

/// Canonicalize `path` and `root` and require `path` to sit inside `root`.
///
/// `Path::starts_with` is reflexive, so the plain check also accepts the root
/// itself. That is fine for anything that reads or writes *into* the root, but
/// fatal for an operation that wipes or removes its target: a game id of `.`
/// would make the target the whole installs directory. `strict` closes that by
/// refusing the root itself.
fn check_path_under_root(path: &Path, root: &Path, strict: bool) -> Result<(), String> {
    check_path_text_before_probe(path, root)?;
    let canonical_root = root.canonicalize().map_err(|error| error.to_string())?;
    let canonical_path = canonicalize_path(path, root)?;
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

/// Is this IPv4 address on the local machine or local network?
/// 127/8, 10/8, 172.16/12, 192.168/16, 169.254/16 and the shared address space
/// 100.64/10 (RFC 6598), where Tailscale puts every peer. Tailscale encrypts the
/// hop. Accepting that range is the companion's own call; the backend's rule for
/// it is the SSRF filter (`_is_blocked_ip` in `oneirodex/utils/security.py`),
/// which counts it as non-public home-lab space.
fn is_private_or_loopback_ipv4(ip: &Ipv4Addr) -> bool {
    let [a, b, _, _] = ip.octets();
    ip.is_loopback()
        || ip.is_private()
        || ip.is_link_local()
        || (a == 100 && (64..=127).contains(&b))
}

/// Same for IPv6: `::1`, unique-local `fc00::/7` (which holds Tailscale's
/// `fd7a:115c:a1e0::/48`), link-local `fe80::/10`, and an IPv4-mapped address
/// (`::ffff:a.b.c.d`) whose embedded IPv4 is itself local.
fn is_private_or_loopback_ipv6(ip: &Ipv6Addr) -> bool {
    if let Some(mapped) = ip.to_ipv4_mapped() {
        return is_private_or_loopback_ipv4(&mapped);
    }
    let first = ip.segments()[0];
    ip.is_loopback() || (first & 0xfe00) == 0xfc00 || (first & 0xffc0) == 0xfe80
}

/// House-network host suffixes a router hands out. The same suffixes as
/// `_PRIVATE_SUFFIXES` in `oneirodex/utils/trusted_host.py`; the address ranges
/// above are the companion's own list.
const PRIVATE_HOST_SUFFIXES: [&str; 5] =
    [".local", ".lan", ".home.arpa", ".internal", ".localdomain"];

/// Does this host name a machine on the user's own network?
///
/// Besides the literal local address ranges: the house-network suffixes
/// (`*.local` mDNS, `*.lan`, `*.home.arpa`, `*.internal`, `*.localdomain`) and
/// `localhost`. Other bare names are not proof of a local destination: resolver
/// search domains can send them elsewhere. Anything with a public-looking dotted
/// name is not local, however much like a LAN address it reads
/// (`192.168.1.1.evil.com`).
fn is_private_or_loopback_host(host: &Host<&str>) -> bool {
    match host {
        Host::Ipv4(ip) => is_private_or_loopback_ipv4(ip),
        Host::Ipv6(ip) => is_private_or_loopback_ipv6(ip),
        Host::Domain(domain) => {
            let name = domain.trim_end_matches('.').to_ascii_lowercase();
            match PRIVATE_HOST_SUFFIXES
                .iter()
                .find_map(|suffix| name.strip_suffix(suffix))
            {
                Some(label) => !label.is_empty(),
                None => name == "localhost",
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
/// `save_config` without going through it. `fixtures/server-urls.json` holds the
/// URLs both implementations are tested against, so they cannot drift apart.
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
                "Refusing http:// for {}: your API token would be sent unencrypted. Use an https:// server URL (plain http:// is only allowed for localhost, private LAN or Tailscale addresses, and .local, .lan, .home.arpa, .internal or .localdomain names; bare host names other than localhost are refused because resolver search domains can send them elsewhere).",
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
    install_recovery::atomic_write(&path, data.as_bytes()).map_err(|error| error.to_string())
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
    install_recovery::atomic_write(&path, data.as_bytes()).map_err(|error| error.to_string())
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
    let summary = install_recovery::retain_missing(&source, &destination)
        .map_err(|error| error.to_string())?;
    log_skipped_links("update", &summary);
    Ok(())
}

/// Linked files are never copied (see `install_recovery::retain_missing`); say so
/// on the companion's own stderr rather than let the copy look complete.
fn log_skipped_links(operation: &str, summary: &install_recovery::RetainSummary) {
    if !summary.skipped_links.is_empty() {
        eprintln!(
            "oneirodex: {operation} did not copy {} symbolic link(s)/junction(s); the data they point at was left where it is",
            summary.skipped_links.len()
        );
    }
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
    let backup = canonicalize_path(&backup, &root)?;
    if backup.exists()
        || source == root.canonicalize().map_err(|error| error.to_string())?
        || backup.starts_with(&source)
    {
        return Err("Invalid install backup destination".into());
    }
    fs::create_dir(&backup).map_err(|error| error.to_string())?;
    let summary =
        install_recovery::retain_missing(&source, &backup).map_err(|error| error.to_string())?;
    log_skipped_links("snapshot", &summary);
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
    let destination = canonicalize_path(&destination, &root)?;
    if destination.exists() || destination.starts_with(&source) || source.starts_with(&destination)
    {
        return Err("Restore destination must be a separate new directory".into());
    }
    fs::create_dir(&destination).map_err(|error| error.to_string())?;
    let summary = install_recovery::retain_missing(&source, &destination)
        .map_err(|error| error.to_string())?;
    log_skipped_links("restore", &summary);
    // `canonicalize` hands back `\\?\C:\…` on Windows. That string ends up in the
    // install record and later in "Show in Explorer", which refuses device-style
    // paths — give the record the ordinary drive path instead.
    Ok(ExtractZipResult {
        extract_path: user_facing_path(&destination.to_string_lossy()),
        exe_path: find_likely_exe(&destination, 2).map(|exe| user_facing_path(&exe)),
    })
}

/// Strip the Win32 verbatim prefix from a drive path (`\\?\C:\x` -> `C:\x`) or a
/// UNC path (`\\?\UNC\host\share` -> `\\host\share`, the form the OS itself reports
/// for a redirected profile folder). Every other shape is returned as is.
fn user_facing_path(path: &str) -> String {
    if let Some(rest) = path.strip_prefix(r"\\?\UNC\") {
        if !rest.is_empty() && !rest.starts_with('\\') {
            return format!(r"\\{rest}");
        }
    }
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
    validate_app_subdir(&subdir)?;
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
    let mods = resolve_subdir(&app, "mods")?;
    let file_path = PathBuf::from(&path);
    ensure_path_under_any_root(&file_path, &[&downloads, &mods])?;
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
async fn extract_zip_archive(
    app: tauri::AppHandle,
    archive_path: String,
    dest_dir: String,
    operation_id: String,
    operations: State<'_, GameArchiveInstallOperations>,
) -> Result<ExtractZipResult, String> {
    if operation_id.trim().is_empty() || operation_id.len() > 128 {
        return Err("Invalid game archive operation id".into());
    }
    let cancellation = Arc::new(AtomicBool::new(false));
    {
        let mut active = operations
            .0
            .lock()
            .map_err(|_| "Could not start game archive extraction".to_string())?;
        if active.contains_key(&operation_id) {
            return Err("Game archive operation is already active".into());
        }
        active.insert(operation_id.clone(), cancellation.clone());
    }
    let operations = operations.0.clone();
    let progress_app = app.clone();
    let progress_operation_id = operation_id.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let _cleanup = GameArchiveOperationCleanup {
            operations,
            operation_id,
        };
        let downloads = resolve_subdir(&app, "downloads")?;
        let installs = resolve_subdir(&app, "installs")?;
        ensure_path_under_root(Path::new(&archive_path), &downloads)?;
        ensure_path_strictly_under_root(Path::new(&dest_dir), &installs)?;
        extract_zip_to_dir_with_configured_budget_and_control(
            Path::new(&archive_path),
            Path::new(&dest_dir),
            &cancellation,
            |bytes_extracted, total_bytes| {
                let _ = progress_app.emit(
                    "game-archive-progress",
                    GameArchiveProgress {
                        operation_id: progress_operation_id.clone(),
                        bytes_extracted,
                        total_bytes,
                    },
                );
            },
        )
    })
    .await
    .map_err(|error| format!("Game archive extraction task failed: {error}"))?
}

#[tauri::command]
fn cancel_game_archive_install(
    operation_id: String,
    operations: State<'_, GameArchiveInstallOperations>,
) -> Result<bool, String> {
    let active = operations
        .0
        .lock()
        .map_err(|_| "Could not cancel game archive extraction".to_string())?;
    Ok(active
        .get(&operation_id)
        .map(|cancellation| !cancellation.swap(true, Ordering::Relaxed))
        .unwrap_or(false))
}

/// The containment rules of `extract_zip_archive`, without the `AppHandle`.
///
/// The destination must be strictly *below* the installs root: a destination
/// equal to the root (a game id of `.`) would replace every installed game.
#[cfg(test)]
fn extract_zip_within_roots(
    archive: &Path,
    destination: &Path,
    downloads: &Path,
    installs: &Path,
) -> Result<ExtractZipResult, String> {
    ensure_path_under_root(archive, downloads)?;
    ensure_path_strictly_under_root(destination, installs)?;
    extract_zip_to_dir_with_configured_budget(archive, destination)
}

const MAX_GAME_ARCHIVE_FILE_BYTES: u64 = 100 * 1024 * 1024 * 1024;
const MAX_GAME_ARCHIVE_ENTRIES: u64 = 250_000;
const MAX_GAME_ARCHIVE_EXPANDED_BYTES: u64 = 200 * 1024 * 1024 * 1024;
const DEFAULT_GAME_ARCHIVE_RESERVE_BYTES: u64 = 1024 * 1024 * 1024;
const GAME_INSTALL_READY_MARKER: &str = ".oneirodex-ready-";
static NEXT_GAME_ARCHIVE_STAGE: AtomicU64 = AtomicU64::new(0);
#[cfg(test)]
thread_local! {
    static GAME_ARCHIVE_TEST_ENOSPC_AFTER: Cell<Option<u64>> = const { Cell::new(None) };
}

fn game_install_lock(parent: &Path, name: &str) -> Result<File, String> {
    let path = parent.join(format!(".{name}.install.lock"));
    let lock = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(path)
        .map_err(|error| format!("Could not open the game install lock: {error}"))?;
    lock.lock_exclusive()
        .map_err(|error| format!("Could not acquire the game install lock: {error}"))?;
    Ok(lock)
}

fn remove_recovery_directory(path: &Path) -> Result<(), String> {
    let metadata = fs::symlink_metadata(path)
        .map_err(|error| format!("Could not inspect interrupted game install: {error}"))?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err("Interrupted game install path is not a real directory".into());
    }
    fs::remove_dir_all(path)
        .map_err(|error| format!("Could not clean interrupted game install: {error}"))
}

fn recover_interrupted_install(destination: &Path) -> Result<(), String> {
    let parent = destination
        .parent()
        .ok_or_else(|| "Install destination has no parent directory".to_string())?;
    let name = destination
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("install");
    let stage_prefix = format!(".{name}.staging-");
    let previous_prefix = format!(".{name}.previous-");
    let ready_prefix = format!(".{name}{GAME_INSTALL_READY_MARKER}");
    let pending_prefix = format!(".{name}.ready-pending-");
    let mut stages = Vec::new();
    let mut previous = Vec::new();
    let mut ready_markers = Vec::new();
    let mut pending_markers = Vec::new();
    for entry in fs::read_dir(parent).map_err(|error| error.to_string())? {
        let entry = entry.map_err(|error| error.to_string())?;
        let filename = entry.file_name();
        let Some(filename) = filename.to_str() else {
            continue;
        };
        let (prefix, kind) = if filename.starts_with(&stage_prefix) {
            (&stage_prefix, 0)
        } else if filename.starts_with(&previous_prefix) {
            (&previous_prefix, 1)
        } else if filename.starts_with(&ready_prefix) {
            (&ready_prefix, 2)
        } else if filename.starts_with(&pending_prefix) {
            (&pending_prefix, 3)
        } else {
            continue;
        };
        let suffix = &filename[prefix.len()..];
        let Some((process_id, counter)) = suffix.split_once('-') else {
            return Err("Interrupted game install has an invalid recovery identifier".into());
        };
        if process_id.parse::<u32>().is_err() || counter.parse::<u64>().is_err() {
            return Err("Interrupted game install has an invalid recovery identifier".into());
        }
        let path = entry.path();
        let metadata = fs::symlink_metadata(&path).map_err(|error| error.to_string())?;
        if kind == 2 || kind == 3 {
            if metadata.file_type().is_symlink() || !metadata.is_file() {
                return Err("Game install recovery marker is not a regular file".into());
            }
            if kind == 2 && fs::read(&path).map_err(|error| error.to_string())? != suffix.as_bytes()
            {
                return Err("Game install recovery marker is invalid".into());
            }
            if kind == 2 {
                ready_markers.push((suffix.to_string(), path));
            } else {
                pending_markers.push(path);
            }
        } else {
            if metadata.file_type().is_symlink() || !metadata.is_dir() {
                return Err("Interrupted game install path is not a real directory".into());
            }
            if kind == 0 {
                stages.push((suffix.to_string(), path));
            } else {
                previous.push((suffix.to_string(), path));
            }
        }
    }

    let destination_exists = match fs::symlink_metadata(destination) {
        Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_dir() => {
            return Err("Install destination is not a real directory".into());
        }
        Ok(_) => true,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => false,
        Err(error) => return Err(format!("Could not inspect install destination: {error}")),
    };
    if ready_markers.len() > 1 || previous.len() > 1 {
        return Err("Multiple interrupted game installs need manual recovery".into());
    }
    if let Some((ready_id, ready_marker)) = ready_markers.first() {
        if previous.iter().any(|(id, _)| id != ready_id) {
            return Err("Interrupted game install has conflicting previous data".into());
        }
        let ready_stage = stages
            .iter()
            .find(|(id, _)| id == ready_id)
            .map(|(_, path)| path);
        let matching_previous = previous
            .iter()
            .find(|(id, _)| id == ready_id)
            .map(|(_, path)| path);
        if let Some(stage) = ready_stage {
            if destination_exists && matching_previous.is_some() {
                return Err(
                    "Interrupted game install has conflicting destination and previous data".into(),
                );
            }
            if !destination_exists {
                if let Some(old_install) = matching_previous {
                    fs::rename(old_install, destination).map_err(|error| {
                        format!("Could not restore the previous game install: {error}")
                    })?;
                } else {
                    fs::rename(stage, destination).map_err(|error| {
                        format!("Could not recover the completed game install: {error}")
                    })?;
                }
            }
            for (_, path) in &stages {
                if path.exists() {
                    remove_recovery_directory(path)?;
                }
            }
            for (id, path) in &previous {
                if id == ready_id && path.exists() {
                    remove_recovery_directory(path)?;
                }
            }
        } else if destination_exists {
            for (_, path) in stages.iter().chain(previous.iter()) {
                remove_recovery_directory(path)?;
            }
        } else if let Some((_, old_install)) = previous.first() {
            fs::rename(old_install, destination)
                .map_err(|error| format!("Could not restore the previous game install: {error}"))?;
            for (_, path) in &stages {
                remove_recovery_directory(path)?;
            }
        } else {
            return Err(
                "Completed game install data is missing; recovery files were preserved".into(),
            );
        }
        fs::remove_file(ready_marker)
            .map_err(|error| format!("Could not finalize recovered game install: {error}"))?;
    } else if !destination_exists {
        if let Some((_, old_install)) = previous.first() {
            fs::rename(old_install, destination)
                .map_err(|error| format!("Could not restore the previous game install: {error}"))?;
        }
        for (_, path) in &stages {
            remove_recovery_directory(path)?;
        }
    } else {
        if !previous.is_empty() {
            return Err(
                "Interrupted game install has conflicting destination and previous data".into(),
            );
        }
        for (_, path) in &stages {
            remove_recovery_directory(path)?;
        }
    }
    for marker in pending_markers {
        fs::remove_file(marker)
            .map_err(|error| format!("Could not clean incomplete recovery marker: {error}"))?;
    }
    Ok(())
}

fn mark_install_stage_ready(parent: &Path, name: &str, suffix: &str) -> Result<PathBuf, String> {
    let marker_path = parent.join(format!(".{name}{GAME_INSTALL_READY_MARKER}{suffix}"));
    let pending_path = parent.join(format!(".{name}.ready-pending-{suffix}"));
    let _pending_cleanup = RecoveryMarkerCleanup {
        path: pending_path.clone(),
        keep: false,
    };
    let mut marker = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&pending_path)
        .map_err(|error| format!("Could not mark game install stage complete: {error}"))?;
    marker
        .write_all(suffix.as_bytes())
        .and_then(|_| marker.sync_all())
        .map_err(|error| format!("Could not persist game install recovery marker: {error}"))?;
    fs::rename(&pending_path, &marker_path)
        .map_err(|error| format!("Could not publish game install recovery marker: {error}"))?;
    Ok(marker_path)
}

#[cfg(test)]
fn exit_at_archive_install_test_point(point: &str) {
    if std::env::var("ONEIRODEX_ARCHIVE_CRASH_TEST_POINT").as_deref() == Ok(point) {
        // `exit` skips Rust destructors, matching a process disappearing at
        // this durable filesystem boundary without abort-dialog behavior.
        std::process::exit(86);
    }
}

fn configured_archive_limit(raw: Option<&str>, default: u64) -> u64 {
    raw.and_then(|value| value.trim().parse::<u64>().ok())
        .filter(|value| *value > 0)
        .unwrap_or(default)
}

fn configured_game_archive_entry_limit(raw: Option<&str>) -> u64 {
    configured_archive_limit(raw, MAX_GAME_ARCHIVE_ENTRIES)
}

#[cfg(test)]
fn extract_zip_to_dir_with_configured_budget(
    archive: &Path,
    destination: &Path,
) -> Result<ExtractZipResult, String> {
    extract_zip_to_dir_with_configured_budget_and_control(
        archive,
        destination,
        &AtomicBool::new(false),
        |_, _| {},
    )
}

fn extract_zip_to_dir_with_configured_budget_and_control(
    archive: &Path,
    destination: &Path,
    cancellation: &AtomicBool,
    on_progress: impl FnMut(u64, u64),
) -> Result<ExtractZipResult, String> {
    let max_entries = configured_game_archive_entry_limit(
        std::env::var("ONEIRODEX_DESKTOP_MAX_GAME_ARCHIVE_ENTRIES")
            .ok()
            .as_deref(),
    );
    let max_expanded_bytes = configured_archive_limit(
        std::env::var("ONEIRODEX_DESKTOP_MAX_GAME_ARCHIVE_EXPANDED_BYTES")
            .ok()
            .as_deref(),
        MAX_GAME_ARCHIVE_EXPANDED_BYTES,
    );
    let reserve_bytes = std::env::var("ONEIRODEX_DESKTOP_GAME_ARCHIVE_RESERVE_BYTES")
        .ok()
        .and_then(|value| value.trim().parse::<u64>().ok())
        .unwrap_or(DEFAULT_GAME_ARCHIVE_RESERVE_BYTES);
    let mut on_progress = on_progress;
    let mut control = GameArchiveExtractionControl {
        cancellation: Some(cancellation),
        on_progress: &mut on_progress,
    };
    extract_zip_to_dir_with_space_budget_and_control(
        archive,
        destination,
        max_entries,
        max_expanded_bytes,
        reserve_bytes,
        None,
        &mut control,
    )
}

fn validate_game_zip_limits(
    zip: &mut ZipArchive<File>,
    max_entries: u64,
    max_expanded_bytes: u64,
) -> Result<u64, String> {
    let entry_count = zip.len() as u64;
    if entry_count > max_entries {
        return Err(format!(
            "Game archive exceeds the {max_entries}-entry limit"
        ));
    }

    let mut expanded_bytes = 0_u64;
    for index in 0..zip.len() {
        let entry = zip.by_index(index).map_err(|error| error.to_string())?;
        if entry.enclosed_name().is_none() {
            return Err("Game archive contains an unsafe entry path".into());
        }
        expanded_bytes = expanded_bytes
            .checked_add(entry.size())
            .ok_or_else(|| "Game archive expanded size overflow".to_string())?;
        if expanded_bytes > max_expanded_bytes {
            return Err(format!(
                "Game archive exceeds the {} GiB expanded-size limit",
                max_expanded_bytes / (1024 * 1024 * 1024)
            ));
        }
    }
    Ok(expanded_bytes)
}

/// Extract every entry of `archive` under `destination`, restoring unix
/// permission bits, and return the extract path plus a best-guess entry point.
///
/// Split out from `extract_zip_archive` so the zip-slip / `enclosed_name()`
/// handling is unit-testable without a `tauri::AppHandle`. The command wrapper
/// still owns the app-root containment check on `archive` / `destination`.
#[cfg(test)]
fn extract_zip_to_dir(archive: &Path, destination: &Path) -> Result<ExtractZipResult, String> {
    extract_zip_to_dir_with_limits(
        archive,
        destination,
        MAX_GAME_ARCHIVE_ENTRIES,
        MAX_GAME_ARCHIVE_EXPANDED_BYTES,
    )
}

#[cfg(test)]
fn extract_zip_to_dir_with_limits(
    archive: &Path,
    destination: &Path,
    max_entries: u64,
    max_expanded_bytes: u64,
) -> Result<ExtractZipResult, String> {
    extract_zip_to_dir_with_space_budget(
        archive,
        destination,
        max_entries,
        max_expanded_bytes,
        0,
        None,
    )
}

#[cfg(test)]
fn extract_zip_to_dir_with_space_budget(
    archive: &Path,
    destination: &Path,
    max_entries: u64,
    max_expanded_bytes: u64,
    reserve_bytes: u64,
    available_bytes_override: Option<u64>,
) -> Result<ExtractZipResult, String> {
    let mut on_progress = |_, _| {};
    let mut control = GameArchiveExtractionControl {
        cancellation: None,
        on_progress: &mut on_progress,
    };
    extract_zip_to_dir_with_space_budget_and_control(
        archive,
        destination,
        max_entries,
        max_expanded_bytes,
        reserve_bytes,
        available_bytes_override,
        &mut control,
    )
}

struct GameArchiveExtractionControl<'a> {
    cancellation: Option<&'a AtomicBool>,
    on_progress: &'a mut dyn FnMut(u64, u64),
}

fn extract_zip_to_dir_with_space_budget_and_control(
    archive: &Path,
    destination: &Path,
    max_entries: u64,
    max_expanded_bytes: u64,
    reserve_bytes: u64,
    available_bytes_override: Option<u64>,
    control: &mut GameArchiveExtractionControl<'_>,
) -> Result<ExtractZipResult, String> {
    if !archive.is_file() {
        return Err(format!("Archive not found: {}", archive.display()));
    }
    let archive_size = fs::metadata(archive)
        .map_err(|error| error.to_string())?
        .len();
    if archive_size > MAX_GAME_ARCHIVE_FILE_BYTES {
        return Err("Game archive exceeds the 100 GiB download limit".into());
    }

    let file = File::open(archive).map_err(|error| error.to_string())?;
    let mut zip = ZipArchive::new(file).map_err(|error| error.to_string())?;
    // Validate the central directory and declared expanded sizes before
    // removing an existing installation at the destination.
    let declared_expanded_bytes =
        validate_game_zip_limits(&mut zip, max_entries, max_expanded_bytes)?;
    if control
        .cancellation
        .is_some_and(|flag| flag.load(Ordering::Relaxed))
    {
        return Err("Game archive extraction canceled".into());
    }

    let parent = destination
        .parent()
        .ok_or_else(|| "Install destination has no parent directory".to_string())?;
    fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    let name = destination
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("install");
    let _install_lock = game_install_lock(parent, name)?;
    recover_interrupted_install(destination)?;
    let required_bytes = declared_expanded_bytes
        .checked_add(reserve_bytes)
        .ok_or_else(|| "Game archive free-space requirement overflow".to_string())?;
    let available_bytes = match available_bytes_override {
        Some(bytes) => bytes,
        None => available_space(parent).map_err(|_| {
            "Could not determine free space for the install destination".to_string()
        })?,
    };
    if available_bytes < required_bytes {
        let gib = 1024 * 1024 * 1024;
        let expanded_gib = declared_expanded_bytes / gib
            + if declared_expanded_bytes % gib == 0 {
                0
            } else {
                1
            };
        return Err(format!(
            "Not enough free space for this game archive: needs {} GiB plus reserve, has {} GiB available",
            expanded_gib,
            available_bytes / gib,
        ));
    }
    let (suffix, staging, backup) = loop {
        let id = NEXT_GAME_ARCHIVE_STAGE.fetch_add(1, Ordering::Relaxed);
        let suffix = format!("{}-{id}", std::process::id());
        let staging = parent.join(format!(".{name}.staging-{suffix}"));
        let backup = parent.join(format!(".{name}.previous-{suffix}"));
        match fs::create_dir(&staging) {
            Ok(()) => break (suffix, staging, backup),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(error.to_string()),
        }
    };
    let _staging_cleanup = DirectoryCleanup(staging.clone());

    let mut expanded_bytes = 0_u64;
    let mut buffer = [0_u8; 64 * 1024];
    (control.on_progress)(0, declared_expanded_bytes);

    for index in 0..zip.len() {
        if control
            .cancellation
            .is_some_and(|flag| flag.load(Ordering::Relaxed))
        {
            return Err("Game archive extraction canceled".into());
        }
        let mut entry = zip.by_index(index).map_err(|error| error.to_string())?;
        // `enclosed_name()` returns `None` for any entry name that would escape
        // the destination (`..` segments, absolute paths, drive letters). The
        // preflight rejects these entries; keep the check here as defense in depth.
        let entry_path = match entry.enclosed_name() {
            Some(path) => staging.join(path),
            None => return Err("Game archive contains an unsafe entry path".into()),
        };

        // Defence in depth: `enclosed_name()` already blocks traversal, but a
        // future swap of the zip crate must not be able to silently reintroduce
        // zip-slip. A join that lands outside staging fails the whole operation.
        if !entry_path.starts_with(&staging) {
            return Err("Game archive entry escapes the install directory".into());
        }

        if entry
            .name()
            .map_err(|error| error.to_string())?
            .ends_with('/')
        {
            fs::create_dir_all(&entry_path).map_err(|error| error.to_string())?;
            continue;
        }

        if let Some(parent) = entry_path.parent() {
            fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }

        let mut out = File::create(&entry_path).map_err(|error| error.to_string())?;
        loop {
            if control
                .cancellation
                .is_some_and(|flag| flag.load(Ordering::Relaxed))
            {
                return Err("Game archive extraction canceled".into());
            }
            use std::io::Read;
            let read = entry.read(&mut buffer).map_err(|error| error.to_string())?;
            if read == 0 {
                break;
            }
            expanded_bytes = expanded_bytes
                .checked_add(read as u64)
                .ok_or_else(|| "Game archive expanded size overflow".to_string())?;
            if expanded_bytes > max_expanded_bytes {
                return Err(format!(
                    "Game archive exceeds the {} GiB expanded-size limit",
                    max_expanded_bytes / (1024 * 1024 * 1024)
                ));
            }
            #[cfg(test)]
            if let Some(fail_after) = GAME_ARCHIVE_TEST_ENOSPC_AFTER.with(Cell::get) {
                let before_chunk = expanded_bytes - read as u64;
                if expanded_bytes > fail_after {
                    let writable =
                        fail_after.saturating_sub(before_chunk).min(read as u64) as usize;
                    if writable > 0 {
                        out.write_all(&buffer[..writable])
                            .map_err(|error| error.to_string())?;
                    }
                    return Err("simulated disk full: no space left on device".into());
                }
            }
            out.write_all(&buffer[..read])
                .map_err(|error| error.to_string())?;
            (control.on_progress)(expanded_bytes, declared_expanded_bytes);
        }

        // Restore the archived permission bits on unix. Without this every
        // extracted file lands 0644 and `launch_game` fails with "permission
        // denied" on the one file that was supposed to be the entry point —
        // and `find_likely_exe` cannot see it either, because the executable
        // bit is the only thing that marks an entry point on a platform with
        // no `.exe` extension. Archives authored on Windows carry no unix mode
        // at all; those stay 0644, which is correct — a Windows build is not
        // launchable here regardless. Never preserve SUID/SGID/sticky bits
        // supplied by an archive; installed game files must not gain special
        // privileges from untrusted ZIP metadata.
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            if let Some(mode) = entry.unix_mode() {
                fs::set_permissions(
                    &entry_path,
                    fs::Permissions::from_mode(safe_archive_file_mode(mode)),
                )
                .map_err(|error| error.to_string())?;
            }
        }
    }

    #[cfg(test)]
    exit_at_archive_install_test_point("after_extract_before_ready");
    if control
        .cancellation
        .is_some_and(|flag| flag.load(Ordering::Relaxed))
    {
        return Err("Game archive extraction canceled".into());
    }
    let ready_marker = mark_install_stage_ready(parent, name, &suffix)?;
    let mut marker_cleanup = RecoveryMarkerCleanup {
        path: ready_marker.clone(),
        keep: false,
    };
    let staged_exe_path = find_likely_exe(&staging, 2).map(PathBuf::from);

    if control
        .cancellation
        .is_some_and(|flag| flag.load(Ordering::Relaxed))
    {
        return Err("Game archive extraction canceled".into());
    }
    let had_destination = destination.exists();
    if had_destination {
        fs::rename(destination, &backup).map_err(|error| error.to_string())?;
        #[cfg(test)]
        exit_at_archive_install_test_point("after_previous_rename");
    }
    if let Err(error) = fs::rename(&staging, destination) {
        if had_destination && fs::rename(&backup, destination).is_err() {
            return Err(format!(
                "Could not promote the staged install ({error}); the previous install remains at {}",
                backup.display()
            ));
        }
        return Err(error.to_string());
    }
    #[cfg(test)]
    exit_at_archive_install_test_point("after_stage_promotion");
    marker_cleanup.keep = true;
    let mut previous_removed = !had_destination;
    if had_destination {
        match remove_path_inner(&backup) {
            Ok(()) => previous_removed = true,
            Err(error) => {
                eprintln!("[desktop] could not remove the superseded install directory: {error}");
            }
        }
    }
    if previous_removed {
        match fs::remove_file(&ready_marker) {
            Ok(()) => marker_cleanup.keep = false,
            Err(error) => {
                eprintln!("[desktop] could not remove the completed install marker: {error}");
            }
        }
    }

    let exe_path = staged_exe_path.map(|path| {
        destination
            .join(path.strip_prefix(&staging).unwrap_or(path.as_path()))
            .to_string_lossy()
            .into_owned()
    });
    Ok(ExtractZipResult {
        extract_path: destination.to_string_lossy().into_owned(),
        exe_path,
    })
}

struct DirectoryCleanup(PathBuf);

impl Drop for DirectoryCleanup {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

struct RecoveryMarkerCleanup {
    path: PathBuf,
    keep: bool,
}

impl Drop for RecoveryMarkerCleanup {
    fn drop(&mut self) {
        if !self.keep {
            let _ = fs::remove_file(&self.path);
        }
    }
}

/// Keep ordinary read/write/execute bits from ZIP metadata while discarding
/// SUID, SGID, and sticky bits that must never be applied to extracted files.
#[cfg(any(unix, test))]
fn safe_archive_file_mode(mode: u32) -> u32 {
    mode & 0o777
}

#[tauri::command]
fn launch_game(
    app: tauri::AppHandle,
    processes: tauri::State<'_, ManagedProcessRegistry>,
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
    let pid = processes.track(child)?;

    Ok(LaunchGameResult {
        pid,
        exe_path: resolved.to_string_lossy().into_owned(),
        resolved_exe_path: if had_exe_path {
            None
        } else {
            Some(resolved.to_string_lossy().into_owned())
        },
    })
}

#[tauri::command]
fn is_process_running(
    processes: tauri::State<'_, ManagedProcessRegistry>,
    pid: u32,
) -> Result<bool, String> {
    process_running_in_registry(processes.inner(), pid)
}

fn process_running_in_registry(
    processes: &ManagedProcessRegistry,
    pid: u32,
) -> Result<bool, String> {
    // A numeric PID can name an unrelated process after exit or restart.
    // Only this registry's retained child is evidence of a running game.
    Ok(processes.is_running(pid)?.unwrap_or(false))
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
#[serde(rename_all = "camelCase")]
pub struct ApplyStagedModResult {
    pub applied: u32,
    pub expanded_bytes: u64,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct StagedModStats {
    pub entry_count: u64,
    pub expanded_bytes: u64,
}

const MAX_MOD_ARCHIVE_ENTRIES: u64 = 50_000;
const MAX_MOD_ARCHIVE_EXPANDED_BYTES: u64 = 4 * 1024 * 1024 * 1024;

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

fn staged_mod_stats_with_limits(
    path: &Path,
    max_entries: u64,
    max_expanded_bytes: u64,
) -> Result<StagedModStats, String> {
    if path
        .extension()
        .and_then(|ext| ext.to_str())
        .is_some_and(|ext| ext.eq_ignore_ascii_case("7z"))
    {
        return Err(
            "7z mod archives are not supported; use a ZIP archive or a direct mod file".into(),
        );
    }
    if is_mod_zip_path(path) {
        let file = File::open(path).map_err(|error| error.to_string())?;
        let mut zip = ZipArchive::new(file).map_err(|error| error.to_string())?;
        if zip.len() as u64 > max_entries {
            return Err(format!("Mod archive exceeds the {max_entries}-entry limit"));
        }
        let mut expanded_bytes = 0_u64;
        for index in 0..zip.len() {
            let entry = zip.by_index(index).map_err(|error| error.to_string())?;
            expanded_bytes = expanded_bytes
                .checked_add(entry.size())
                .ok_or_else(|| "Mod archive expanded size overflow".to_string())?;
            if expanded_bytes > max_expanded_bytes {
                return Err(format!(
                    "Mod archive exceeds the {} GiB expanded-size limit",
                    max_expanded_bytes / (1024 * 1024 * 1024)
                ));
            }
        }
        Ok(StagedModStats {
            entry_count: zip.len() as u64,
            expanded_bytes,
        })
    } else {
        let metadata = fs::metadata(path).map_err(|error| error.to_string())?;
        if metadata.len() > max_expanded_bytes {
            return Err(format!(
                "Mod file exceeds the {} GiB size limit",
                max_expanded_bytes / (1024 * 1024 * 1024)
            ));
        }
        Ok(StagedModStats {
            entry_count: 1,
            expanded_bytes: metadata.len(),
        })
    }
}

fn staged_mod_stats(path: &Path) -> Result<StagedModStats, String> {
    staged_mod_stats_with_limits(
        path,
        MAX_MOD_ARCHIVE_ENTRIES,
        MAX_MOD_ARCHIVE_EXPANDED_BYTES,
    )
}

/// Resolve a ZIP member beneath an existing install root without following a
/// symlink that escapes that root. Mods are extracted into an existing game
/// tree, so lexical `enclosed_name()` checks alone do not prevent writes
/// through a pre-existing symlink.
fn safe_mod_entry_path(
    root: &Path,
    relative: &Path,
    create_directory: bool,
) -> Result<PathBuf, String> {
    let canonical_root = root.canonicalize().map_err(|error| error.to_string())?;
    let components: Vec<_> = relative.components().collect();
    if components.is_empty()
        || components
            .iter()
            .any(|component| !matches!(component, std::path::Component::Normal(_)))
    {
        return Err("Invalid mod archive entry path".into());
    }

    let mut current = canonical_root.clone();
    for (index, component) in components.iter().enumerate() {
        current.push(component);
        let leaf = index + 1 == components.len();
        if !leaf || create_directory {
            if !current.exists() {
                fs::create_dir(&current).map_err(|error| error.to_string())?;
            }
            let resolved = current.canonicalize().map_err(|error| error.to_string())?;
            if !resolved.starts_with(&canonical_root) || !resolved.is_dir() {
                return Err("Mod archive entry escapes the install directory".into());
            }
            current = resolved;
        } else if fs::symlink_metadata(&current).is_ok() {
            let resolved = current.canonicalize().map_err(|error| error.to_string())?;
            if !resolved.starts_with(&canonical_root) {
                return Err("Mod archive entry escapes the install directory".into());
            }
            current = resolved;
        }
    }
    Ok(current)
}

fn extract_staged_mod_zip(
    zip: &mut ZipArchive<File>,
    destination_root: &Path,
) -> Result<(u32, u64), String> {
    if zip.len() as u64 > MAX_MOD_ARCHIVE_ENTRIES {
        return Err(format!(
            "Mod archive exceeds the {MAX_MOD_ARCHIVE_ENTRIES}-entry limit"
        ));
    }
    let mut declared_bytes = 0_u64;
    for index in 0..zip.len() {
        let entry = zip.by_index(index).map_err(|error| error.to_string())?;
        declared_bytes = declared_bytes
            .checked_add(entry.size())
            .ok_or_else(|| "Mod archive expanded size overflow".to_string())?;
        if declared_bytes > MAX_MOD_ARCHIVE_EXPANDED_BYTES {
            return Err(format!(
                "Mod archive exceeds the {} GiB expanded-size limit",
                MAX_MOD_ARCHIVE_EXPANDED_BYTES / (1024 * 1024 * 1024)
            ));
        }
    }
    let mut applied = 0;
    let mut expanded_bytes = 0_u64;
    let mut buffer = [0_u8; 64 * 1024];
    for index in 0..zip.len() {
        let mut entry = zip.by_index(index).map_err(|error| error.to_string())?;
        let relative = match entry.enclosed_name() {
            Some(path) => path,
            None => continue,
        };
        let is_directory = entry
            .name()
            .map_err(|error| error.to_string())?
            .ends_with('/');
        let entry_path = safe_mod_entry_path(destination_root, &relative, is_directory)?;
        if is_directory {
            continue;
        }
        let mut out = File::create(&entry_path).map_err(|error| error.to_string())?;
        loop {
            use std::io::Read;
            let read = entry.read(&mut buffer).map_err(|error| error.to_string())?;
            if read == 0 {
                break;
            }
            expanded_bytes = expanded_bytes
                .checked_add(read as u64)
                .ok_or_else(|| "Mod archive expanded size overflow".to_string())?;
            if expanded_bytes > MAX_MOD_ARCHIVE_EXPANDED_BYTES {
                return Err(format!(
                    "Mod archive exceeds the {} GiB expanded-size limit",
                    MAX_MOD_ARCHIVE_EXPANDED_BYTES / (1024 * 1024 * 1024)
                ));
            }
            out.write_all(&buffer[..read])
                .map_err(|error| error.to_string())?;
        }
        applied += 1;
    }
    Ok((applied, expanded_bytes))
}

#[tauri::command]
fn inspect_staged_mod(
    app: tauri::AppHandle,
    source_path: String,
) -> Result<StagedModStats, String> {
    let mods = resolve_subdir(&app, "mods")?;
    let source = PathBuf::from(&source_path);
    ensure_path_under_root(&source, &mods)?;
    if !source.is_file() {
        return Err("Staged mod file not found".into());
    }
    staged_mod_stats(&source)
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

    let stats = staged_mod_stats(&source)?;
    let (applied, expanded_bytes) = if is_mod_zip_path(&source) {
        let file = File::open(&source).map_err(|error| error.to_string())?;
        let mut zip = ZipArchive::new(file).map_err(|error| error.to_string())?;
        extract_staged_mod_zip(&mut zip, &destination_root)?
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
        (1, stats.expanded_bytes)
    };

    Ok(ApplyStagedModResult {
        applied,
        expanded_bytes,
    })
}

#[tauri::command]
fn get_flips_path() -> Result<String, String> {
    Ok(std::env::var("FLIPS_PATH").unwrap_or_default())
}

/// Apply an IPS/BPS patch with Flips. Paths must live under app_data/patches.
///
/// The Flips program comes only from the `FLIPS_PATH` environment variable.
/// It used to accept a path from the webview too, which made this the one
/// command that would run any program the page named.
#[tauri::command]
fn run_flips_apply(
    app: tauri::AppHandle,
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

    let flips = std::env::var("FLIPS_PATH")
        .ok()
        .filter(|v| !v.trim().is_empty())
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

fn trusted_shares_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    Ok(app_data_dir(app)?.join("trusted_shares.json"))
}

/// The network shares the user listed under *Trusted network shares*.
#[tauri::command]
fn load_trusted_shares(app: tauri::AppHandle) -> Result<Vec<String>, String> {
    Ok(trusted_shares::read_share_roots(&trusted_shares_path(
        &app,
    )?))
}

/// Replace the list. Every entry is validated first and one bad entry fails the
/// whole save, so the list on disk is always one the user actually meant. Returns
/// the canonical form that was stored.
#[tauri::command]
fn save_trusted_shares(app: tauri::AppHandle, roots: Vec<String>) -> Result<Vec<String>, String> {
    let normalized = trusted_shares::normalize_share_roots(&roots)?;
    let data = serde_json::to_string_pretty(&serde_json::json!({ "roots": &normalized }))
        .map_err(|error| error.to_string())?;
    install_recovery::atomic_write(&trusted_shares_path(&app)?, data.as_bytes())
        .map_err(|error| error.to_string())?;
    Ok(normalized)
}

/// UNC folders the OS itself reports for this user (Windows Folder Redirection
/// puts Documents / AppData / the profile on a file server). Those hosts are
/// already trusted by the OS, so paths under them need no entry in the list; a
/// path the server chose that merely *looks* similar still has to match one
/// of these segment for segment.
fn os_reported_share_roots(app: &tauri::AppHandle) -> Vec<String> {
    let resolver = app.path();
    [
        resolver.home_dir(),
        resolver.document_dir(),
        resolver.data_dir(),
        resolver.config_dir(),
        resolver.local_data_dir(),
        resolver.app_data_dir(),
    ]
    .into_iter()
    .filter_map(Result::ok)
    .map(|dir| dir.to_string_lossy().into_owned())
    .filter(|dir| trusted_shares::is_plain_unc(dir))
    .collect()
}

/// Everything a queued `open_path` may reach over the network: the user's list
/// plus the OS-reported roots. Read fresh on every reveal, never cached, and never
/// supplied by the webview — a path the server chose cannot widen it.
fn effective_trusted_shares(app: &tauri::AppHandle) -> Result<Vec<String>, String> {
    let mut shares = trusted_shares::read_share_roots(&trusted_shares_path(app)?);
    shares.extend(os_reported_share_roots(app));
    Ok(shares)
}

/// Shown when a reveal path names a network share or a device. Keep in step with
/// `NETWORK_PATH_REFUSED` in `src/open-path.ts`; a test in `src/open-path.test.ts`
/// reads this file and fails when the two differ.
const NETWORK_PATH_REFUSED: &str =
    "Network (UNC) paths only open for shares you list under Trusted network shares in the companion (or map the share to a drive letter); device paths are always blocked";

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

/// Every check on the text of a reveal path — all of `validate_reveal_path` that
/// does not touch the filesystem. Split out so the decision "may this path be
/// probed at all" is testable without a probe (on Windows a probe of an
/// untrusted UNC path is the very thing being prevented).
fn check_reveal_path_text(trimmed: &str, trusted_shares: &[String]) -> Result<(), String> {
    if trimmed.is_empty() {
        return Err("Path is required".into());
    }
    if trimmed.len() > 4096 {
        return Err("Path is too long".into());
    }
    if trimmed.contains('\0') || trimmed.contains('\n') || trimmed.contains('\r') {
        return Err("Path contains invalid control characters".into());
    }
    if is_network_or_device_path(trimmed)
        && !trusted_shares::is_under_trusted_share(trimmed, trusted_shares)
    {
        return Err(NETWORK_PATH_REFUSED.into());
    }
    if path_has_dotdot_segment(trimmed) {
        return Err("Path must not contain .. segments".into());
    }
    if !is_absolute_os_path(Path::new(trimmed)) {
        return Err("Path must be absolute".into());
    }
    Ok(())
}

/// Validate a caller-supplied reveal path and classify it as a file or directory.
///
/// Every rejection here happens before any OS process is spawned, which is what
/// makes the guard testable in isolation: empty / whitespace-only, longer than
/// 4096 bytes, embedded NUL / CR / LF, a UNC or device path, any `..` path
/// segment, a non-absolute path, or a path that does not exist on this machine.
/// The UNC / device check comes before the first filesystem call (`exists()`).
///
/// A UNC path passes that check only when it sits at or below a share in
/// `trusted_shares` — the shares the user listed, plus the ones the OS itself
/// reports for the user's folders. The match is string-only, so the filesystem is
/// still never touched for a host nobody trusted.
fn validate_reveal_path(
    path: &str,
    trusted_shares: &[String],
) -> Result<(PathBuf, &'static str), String> {
    let trimmed = path.trim();
    check_reveal_path_text(trimmed, trusted_shares)?;

    let target = PathBuf::from(trimmed);
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

/// Does this folder's own name carry an extension (`Evil.app`, `Foo.xcodeproj`)?
///
/// On macOS `open <directory>` only opens a folder when the directory is an
/// ordinary one. A *package* - a directory LaunchServices maps to a handler by
/// its extension - is launched instead: `open Evil.app` runs the app. The set of
/// package extensions is open-ended (`.app`, `.bundle`, `.prefPane`, `.saver`,
/// `.workflow`, `.scptd`, `.xpc`, `.appex`, `.kext`, `.plugin`, `.mpkg`, and
/// whatever a third-party app registers), so no list is kept: a name with an
/// extension is never opened, only revealed.
fn looks_like_package(folder: &Path) -> bool {
    folder
        .file_name()
        .is_some_and(|name| name.to_string_lossy().contains('.'))
}

/// The arguments for `open` when the companion reveals `target` on macOS.
///
/// A queued `open_path` is written by the server, and it can ask for the folder
/// to be opened rather than selected (`select == false`). `open <directory>`
/// would then launch an `.app` the server had just had installed (a zip
/// extraction sets no quarantine attribute), with no click from the user, so
/// the companion never hands `open` a folder that could be a package:
///
/// * `select`: `open -R <target>`. `-R` reveals the item in Finder and never
///   opens it, whatever it is;
/// * otherwise the folder (the target, or a file's parent) is opened only when
///   its name has no extension and it does not resolve (through a symbolic link)
///   to one that has; anything else is revealed with `-R` instead.
///
/// `resolve` maps a folder to its symbolic-link-free form (`fs::canonicalize`
/// in the command, injected so the choice stays a pure function). Every path is
/// absolute (`validate_reveal_path`), so none can be read as an `open` option.
/// Not `cfg(target_os = "macos")` so its tests run on every host.
#[cfg_attr(not(target_os = "macos"), allow(dead_code))]
fn macos_open_args(
    target: &Path,
    target_is_file: bool,
    select_item: bool,
    resolve: impl Fn(&Path) -> PathBuf,
) -> Vec<String> {
    if select_item {
        return vec!["-R".to_string(), target.to_string_lossy().into_owned()];
    }
    let folder = if target_is_file {
        target.parent().unwrap_or(target)
    } else {
        target
    };
    let folder_arg = folder.to_string_lossy().into_owned();
    if looks_like_package(folder) || looks_like_package(&resolve(folder)) {
        return vec!["-R".to_string(), folder_arg];
    }
    vec![folder_arg]
}

/// Open `path` in Explorer (Windows), Finder (macOS), or the default file manager (Linux).
/// When `select` is true and the path is a file, select it in the parent folder.
#[tauri::command]
fn reveal_path_in_os(
    app: tauri::AppHandle,
    path: String,
    select: Option<bool>,
) -> Result<RevealPathResult, String> {
    let trimmed = path.trim();
    let trusted = effective_trusted_shares(&app)?;
    let (target, revealed_as) = validate_reveal_path(trimmed, &trusted)?;
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
        let args = macos_open_args(&target, target.is_file(), select_item, |path| {
            fs::canonicalize(path).unwrap_or_else(|_| path.to_path_buf())
        });
        let status = std::process::Command::new("open")
            .args(args)
            .status()
            .map_err(|error| format!("Failed to start Finder: {error}"))?;
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
        .manage(ManagedProcessRegistry::default())
        .manage(GameArchiveInstallOperations::default())
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
            cancel_game_archive_install,
            launch_game,
            reveal_path_in_os,
            load_trusted_shares,
            save_trusted_shares,
            is_process_running,
            remove_path,
            rename_path,
            get_flips_path,
            run_flips_apply,
            inspect_staged_mod,
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
    use std::process::Command;
    use std::time::{Duration, Instant};
    use tempfile::tempdir;

    #[test]
    fn managed_child_fixture() {
        if std::env::var_os("ONEIRODEX_CHILD_REAP_TEST").is_some() {
            std::thread::sleep(Duration::from_millis(100));
        }
    }

    #[test]
    fn archive_install_crash_fixture_child() {
        let Ok(root) = std::env::var("ONEIRODEX_ARCHIVE_CRASH_TEST_ROOT") else {
            return;
        };
        let root = PathBuf::from(root);
        let archive = root.join("bundle.zip");
        let destination = root.join("install");
        let _ = extract_zip_to_dir(&archive, &destination);
    }

    #[test]
    fn managed_process_waiter_reaps_a_short_lived_child() {
        let child = Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "tests::managed_child_fixture", "--nocapture"])
            .env("ONEIRODEX_CHILD_REAP_TEST", "1")
            .spawn()
            .unwrap();
        let pid = child.id();
        let registry = ManagedProcessRegistry::default();
        assert_eq!(registry.track(child).unwrap(), pid);
        assert_eq!(registry.is_running(pid).unwrap(), Some(true));
        assert!(process_running_in_registry(&registry, pid).unwrap());

        let deadline = Instant::now() + Duration::from_secs(5);
        let mut observed = Some(true);
        while observed == Some(true) && Instant::now() < deadline {
            std::thread::sleep(Duration::from_millis(10));
            observed = registry.is_running(pid).unwrap();
        }

        assert_eq!(observed, Some(false));
        assert!(!process_running_in_registry(&registry, pid).unwrap());
    }

    #[test]
    fn process_status_rejects_an_unregistered_live_pid() {
        let registry = ManagedProcessRegistry::default();
        // This test process is alive, but it was never launched as a game.
        assert!(!process_running_in_registry(&registry, std::process::id()).unwrap());
    }

    #[test]
    fn process_status_does_not_reattach_after_an_exit_was_observed() {
        let registry = ManagedProcessRegistry::default();
        let pid = std::process::id();
        // Model a consumed game exit whose numeric PID now names an unrelated
        // live process. This is deterministic identity substitution, not a
        // claim that the kernel actually recycled a PID in this test.
        registry.0.lock().unwrap().insert(pid, false);
        assert!(!process_running_in_registry(&registry, pid).unwrap());
        assert!(!process_running_in_registry(&registry, pid).unwrap());
    }
    use zip::write::{SimpleFileOptions, ZipWriter};

    #[test]
    fn app_subdir_allows_only_managed_directory_names() {
        for name in ["downloads", "installs", "mods", "patches", "cheats"] {
            assert!(
                validate_app_subdir(name).is_ok(),
                "expected {name} to be allowed"
            );
        }
        for name in [
            "../escape",
            "..\\escape",
            "/tmp/escape",
            "C:\\escape",
            "unknown",
        ] {
            assert!(
                validate_app_subdir(name).is_err(),
                "expected {name} to be rejected"
            );
        }
    }

    /// The reveal tests below run with an empty trust list (nothing on the
    /// network is trusted); the trusted-share cases have their own section.
    fn validate_reveal_path(path: &str) -> Result<(PathBuf, &'static str), String> {
        super::validate_reveal_path(path, &[])
    }

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
    fn under_root_accepts_multiple_missing_staging_directories() {
        let root = tempdir().unwrap();
        let target = root.path().join("patches/game-1/nested/fix.bps");

        assert!(ensure_path_under_root(&target, root.path()).is_ok());
        fs::create_dir_all(target.parent().unwrap()).unwrap();
        fs::write(&target, b"patch").unwrap();
        assert!(ensure_path_under_root(&target, root.path()).is_ok());
    }

    #[cfg(unix)]
    #[test]
    fn under_root_rejects_missing_path_below_existing_symlink_escape() {
        use std::os::unix::fs::symlink;

        let base = tempdir().unwrap();
        let root = base.path().join("patches");
        let outside = base.path().join("outside");
        fs::create_dir_all(&root).unwrap();
        fs::create_dir_all(&outside).unwrap();
        symlink(&outside, root.join("linked-game")).unwrap();
        let target = root.join("linked-game/nested/fix.bps");

        assert!(ensure_path_under_root(&target, &root).is_err());
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

    struct ArchiveEnospcGuard;

    impl ArchiveEnospcGuard {
        fn after(bytes: u64) -> Self {
            GAME_ARCHIVE_TEST_ENOSPC_AFTER.with(|limit| {
                assert!(limit.replace(Some(bytes)).is_none());
            });
            Self
        }
    }

    impl Drop for ArchiveEnospcGuard {
        fn drop(&mut self) {
            GAME_ARCHIVE_TEST_ENOSPC_AFTER.with(|limit| limit.set(None));
        }
    }

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

    fn write_zip_with_raw_unix_mode(path: &Path, name: &str, body: &[u8], mode: u32) {
        write_zip(path, &[(name, body)]);
        let mut archive = fs::read(path).unwrap();
        let central_header = archive
            .windows(4)
            .position(|bytes| bytes == b"PK\x01\x02")
            .expect("ZIP central directory entry");
        // Mark the creator as Unix and put the hostile file mode in the
        // central directory. zip::write::unix_permissions masks these bits,
        // so patch the archive bytes as an attacker would instead.
        archive[central_header + 4..central_header + 6]
            .copy_from_slice(&((3_u16 << 8) | 20).to_le_bytes());
        archive[central_header + 38..central_header + 42]
            .copy_from_slice(&(mode << 16).to_le_bytes());
        fs::write(path, archive).unwrap();
    }

    #[test]
    fn archive_mode_filter_removes_setuid_setgid_and_sticky_bits() {
        let work = tempdir().unwrap();
        let hostile_modes = [0o104755, 0o102750, 0o101755];
        for (index, hostile_mode) in hostile_modes.into_iter().enumerate() {
            let archive = work.path().join(format!("hostile-{index}.zip"));
            write_zip_with_raw_unix_mode(&archive, "game", b"payload", hostile_mode);
            let mut zip = ZipArchive::new(fs::File::open(&archive).unwrap()).unwrap();
            let parsed_mode = zip.by_index(0).unwrap().unix_mode().unwrap();
            // zip 9 filters special permission bits while reading Unix mode
            // metadata; retain the app-level mask as defense in depth.
            assert_eq!(parsed_mode, hostile_mode & !0o7000);

            let safe = safe_archive_file_mode(parsed_mode);
            assert_eq!(safe, hostile_mode & 0o777);
            assert_eq!(safe & 0o7000, 0);
        }
        assert_eq!(safe_archive_file_mode(0o100755), 0o755);
        assert_eq!(safe_archive_file_mode(0o100644), 0o644);
    }

    #[cfg(unix)]
    #[test]
    fn extract_strips_privileged_archive_bits_and_keeps_executable_mode() {
        use std::os::unix::fs::PermissionsExt;

        let work = tempdir().unwrap();
        let archive = work.path().join("privileged.zip");
        write_zip_with_raw_unix_mode(&archive, "game", b"payload", 0o104755);
        let destination = work.path().join("out");

        extract_zip_to_dir(&archive, &destination).unwrap();

        let mode = fs::metadata(destination.join("game"))
            .unwrap()
            .permissions()
            .mode();
        assert_eq!(mode & 0o777, 0o755);
        assert_eq!(mode & 0o7000, 0);
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
    fn game_archive_limits_reject_entry_count_and_expanded_size_before_replacing_install() {
        let work = tempdir().unwrap();
        let archive = work.path().join("bundle.zip");
        write_zip(&archive, &[("one.bin", b"1234"), ("two.bin", b"5678")]);
        let destination = work.path().join("install");
        fs::create_dir_all(&destination).unwrap();
        fs::write(destination.join("existing.bin"), b"keep me").unwrap();

        let entries_error =
            extract_zip_to_dir_with_limits(&archive, &destination, 1, 8).unwrap_err();
        assert!(
            entries_error.contains("1-entry limit"),
            "got: {entries_error}"
        );
        assert_eq!(
            fs::read(destination.join("existing.bin")).unwrap(),
            b"keep me"
        );

        let size_error = extract_zip_to_dir_with_limits(&archive, &destination, 2, 7).unwrap_err();
        assert!(
            size_error.contains("expanded-size limit"),
            "got: {size_error}"
        );
        assert_eq!(
            fs::read(destination.join("existing.bin")).unwrap(),
            b"keep me"
        );

        extract_zip_to_dir_with_limits(&archive, &destination, 2, 8).unwrap();
        assert!(!destination.join("existing.bin").exists());
        assert_eq!(fs::read(destination.join("one.bin")).unwrap(), b"1234");
        assert_eq!(fs::read(destination.join("two.bin")).unwrap(), b"5678");
    }

    #[test]
    fn free_space_preflight_preserves_existing_install_without_staging() {
        let work = tempdir().unwrap();
        let archive = work.path().join("bundle.zip");
        write_zip(&archive, &[("game.bin", b"12345678")]);
        let destination = work.path().join("install");
        fs::create_dir_all(&destination).unwrap();
        fs::write(destination.join("existing.bin"), b"keep me").unwrap();

        let error =
            extract_zip_to_dir_with_space_budget(&archive, &destination, 10, 1024, 1, Some(8))
                .unwrap_err();

        assert!(error.contains("Not enough free space"), "got: {error}");
        assert_eq!(
            fs::read(destination.join("existing.bin")).unwrap(),
            b"keep me"
        );
        assert_eq!(
            fs::read_dir(work.path())
                .unwrap()
                .filter_map(Result::ok)
                .filter(|entry| entry
                    .file_name()
                    .to_string_lossy()
                    .starts_with(".install.staging-"))
                .count(),
            0,
        );

        extract_zip_to_dir_with_space_budget(&archive, &destination, 10, 1024, 1, Some(9)).unwrap();
        assert_eq!(fs::read(destination.join("game.bin")).unwrap(), b"12345678");
    }

    #[test]
    fn cancel_during_streaming_extraction_preserves_previous_install() {
        let work = tempdir().unwrap();
        let archive = work.path().join("bundle.zip");
        let body = vec![b'x'; 256 * 1024];
        write_zip(&archive, &[("game.bin", &body)]);
        let destination = work.path().join("install");
        fs::create_dir_all(&destination).unwrap();
        fs::write(destination.join("game.bin"), b"old generation").unwrap();
        let cancellation = AtomicBool::new(false);
        let mut progress_samples = Vec::new();
        let mut on_progress = |bytes_extracted, total_bytes| {
            progress_samples.push((bytes_extracted, total_bytes));
            if bytes_extracted > 0 {
                cancellation.store(true, Ordering::Relaxed);
            }
        };
        let mut control = GameArchiveExtractionControl {
            cancellation: Some(&cancellation),
            on_progress: &mut on_progress,
        };

        let error = extract_zip_to_dir_with_space_budget_and_control(
            &archive,
            &destination,
            10,
            1024 * 1024,
            0,
            Some(u64::MAX),
            &mut control,
        )
        .unwrap_err();

        assert!(error.contains("extraction canceled"), "got: {error}");
        assert!(progress_samples.len() >= 2);
        assert_eq!(progress_samples[0], (0, body.len() as u64));
        assert!(progress_samples[1].0 > 0);
        assert_eq!(
            fs::read(destination.join("game.bin")).unwrap(),
            b"old generation"
        );
        assert_eq!(
            fs::read_dir(work.path())
                .unwrap()
                .filter_map(Result::ok)
                .filter(|entry| entry
                    .file_name()
                    .to_string_lossy()
                    .starts_with(".install.staging-"))
                .count(),
            0,
        );
    }

    #[test]
    fn process_exit_at_archive_promotion_boundaries_recovers_on_next_install() {
        for (point, expected) in [
            ("after_extract_before_ready", b"old".as_slice()),
            ("after_previous_rename", b"old".as_slice()),
            ("after_stage_promotion", b"new".as_slice()),
        ] {
            let work = tempdir().unwrap();
            let archive = work.path().join("bundle.zip");
            write_zip(&archive, &[("game.bin", b"new")]);
            let destination = work.path().join("install");
            fs::create_dir_all(&destination).unwrap();
            fs::write(destination.join("game.bin"), b"old").unwrap();

            let status = Command::new(std::env::current_exe().unwrap())
                .args([
                    "--exact",
                    "tests::archive_install_crash_fixture_child",
                    "--nocapture",
                ])
                .env("ONEIRODEX_ARCHIVE_CRASH_TEST_ROOT", work.path())
                .env("ONEIRODEX_ARCHIVE_CRASH_TEST_POINT", point)
                .status()
                .unwrap();
            assert_eq!(status.code(), Some(86), "child did not exit at {point}");

            recover_interrupted_install(&destination).unwrap();
            assert_eq!(
                fs::read(destination.join("game.bin")).unwrap(),
                expected,
                "{point}"
            );
            assert!(
                fs::read_dir(work.path()).unwrap().all(|entry| {
                    let name = entry.unwrap().file_name().to_string_lossy().into_owned();
                    !name.starts_with(".install.staging-")
                        && !name.starts_with(".install.previous-")
                        && !name.starts_with(".install.oneirodex-ready-")
                        && !name.starts_with(".install.ready-pending-")
                }),
                "recovery residue after {point}"
            );
        }
    }

    #[test]
    fn interrupted_ready_stage_restores_previous_install_before_new_extract() {
        let work = tempdir().unwrap();
        let destination = work.path().join("install");
        let stage = work.path().join(".install.staging-123-4");
        let previous = work.path().join(".install.previous-123-4");
        fs::create_dir_all(&stage).unwrap();
        fs::write(stage.join("new.bin"), b"new").unwrap();
        mark_install_stage_ready(work.path(), "install", "123-4").unwrap();
        fs::create_dir_all(&previous).unwrap();
        fs::write(previous.join("old.bin"), b"old").unwrap();

        let _lock = game_install_lock(work.path(), "install").unwrap();
        recover_interrupted_install(&destination).unwrap();

        assert_eq!(fs::read(destination.join("old.bin")).unwrap(), b"old");
        assert!(!destination.join("new.bin").exists());
        assert!(!stage.exists());
        assert!(!previous.exists());
        assert!(!work.path().join(".install.oneirodex-ready-123-4").exists());
    }

    #[test]
    fn interrupted_promoted_install_keeps_new_and_cleans_previous_generation() {
        let work = tempdir().unwrap();
        let destination = work.path().join("install");
        let previous = work.path().join(".install.previous-123-4");
        fs::create_dir_all(&destination).unwrap();
        fs::write(destination.join("new.bin"), b"new").unwrap();
        fs::create_dir_all(&previous).unwrap();
        fs::write(previous.join("old.bin"), b"old").unwrap();
        mark_install_stage_ready(work.path(), "install", "123-4").unwrap();

        let _lock = game_install_lock(work.path(), "install").unwrap();
        recover_interrupted_install(&destination).unwrap();

        assert_eq!(fs::read(destination.join("new.bin")).unwrap(), b"new");
        assert!(!previous.exists());
        assert!(!work.path().join(".install.oneirodex-ready-123-4").exists());
    }

    #[test]
    fn interrupted_unready_stage_restores_previous_generation() {
        let work = tempdir().unwrap();
        let destination = work.path().join("install");
        let stage = work.path().join(".install.staging-123-4");
        let previous = work.path().join(".install.previous-123-4");
        fs::create_dir_all(&stage).unwrap();
        fs::write(stage.join("partial.bin"), b"partial").unwrap();
        fs::create_dir_all(&previous).unwrap();
        fs::write(previous.join("old.bin"), b"old").unwrap();

        let _lock = game_install_lock(work.path(), "install").unwrap();
        recover_interrupted_install(&destination).unwrap();

        assert_eq!(fs::read(destination.join("old.bin")).unwrap(), b"old");
        assert!(!stage.exists());
        assert!(!previous.exists());
    }

    #[test]
    fn interrupted_ready_stage_does_not_replace_existing_install_before_swap() {
        let work = tempdir().unwrap();
        let destination = work.path().join("install");
        let stage = work.path().join(".install.staging-123-4");
        fs::create_dir_all(&destination).unwrap();
        fs::write(destination.join("old.bin"), b"old").unwrap();
        fs::create_dir_all(&stage).unwrap();
        fs::write(stage.join("new.bin"), b"new").unwrap();
        mark_install_stage_ready(work.path(), "install", "123-4").unwrap();

        let _lock = game_install_lock(work.path(), "install").unwrap();
        recover_interrupted_install(&destination).unwrap();

        assert_eq!(fs::read(destination.join("old.bin")).unwrap(), b"old");
        assert!(!destination.join("new.bin").exists());
        assert!(!stage.exists());
        assert!(!work.path().join(".install.oneirodex-ready-123-4").exists());
    }

    #[test]
    fn interrupted_marker_write_cleans_partial_stage_and_preserves_existing_install() {
        let work = tempdir().unwrap();
        let destination = work.path().join("install");
        let stage = work.path().join(".install.staging-123-4");
        let pending_marker = work.path().join(".install.ready-pending-123-4");
        fs::create_dir_all(&destination).unwrap();
        fs::write(destination.join("old.bin"), b"old").unwrap();
        fs::create_dir_all(&stage).unwrap();
        fs::write(stage.join("partial.bin"), b"partial").unwrap();
        fs::write(&pending_marker, b"partial marker").unwrap();

        let _lock = game_install_lock(work.path(), "install").unwrap();
        recover_interrupted_install(&destination).unwrap();

        assert_eq!(fs::read(destination.join("old.bin")).unwrap(), b"old");
        assert!(!stage.exists());
        assert!(!pending_marker.exists());
    }

    #[test]
    fn invalid_ready_marker_refuses_cleanup_and_preserves_recovery_data() {
        let work = tempdir().unwrap();
        let destination = work.path().join("install");
        let previous = work.path().join(".install.previous-123-4");
        fs::create_dir_all(&previous).unwrap();
        fs::write(previous.join("old.bin"), b"old").unwrap();
        let marker = work.path().join(".install.oneirodex-ready-123-4");
        fs::write(&marker, b"invalid").unwrap();

        let _lock = game_install_lock(work.path(), "install").unwrap();
        assert!(recover_interrupted_install(&destination).is_err());

        assert!(!destination.exists());
        assert_eq!(fs::read(previous.join("old.bin")).unwrap(), b"old");
        assert!(marker.exists());
    }

    #[test]
    fn missing_ready_stage_and_destination_preserves_marker_for_manual_recovery() {
        let work = tempdir().unwrap();
        let destination = work.path().join("install");
        let marker = work.path().join(".install.oneirodex-ready-123-4");
        fs::write(&marker, b"123-4").unwrap();

        let _lock = game_install_lock(work.path(), "install").unwrap();
        assert!(recover_interrupted_install(&destination).is_err());

        assert!(!destination.exists());
        assert!(marker.exists());
    }

    #[test]
    fn next_extraction_recovers_a_crash_state_before_installing_new_archive() {
        let work = tempdir().unwrap();
        let archive = work.path().join("bundle.zip");
        write_zip(&archive, &[("fresh.bin", b"fresh")]);
        let destination = work.path().join("install");
        let stage = work.path().join(".install.staging-123-4");
        let previous = work.path().join(".install.previous-123-4");
        fs::create_dir_all(&stage).unwrap();
        fs::write(stage.join("staged.bin"), b"complete stage").unwrap();
        mark_install_stage_ready(work.path(), "install", "123-4").unwrap();
        fs::create_dir_all(&previous).unwrap();
        fs::write(previous.join("old.bin"), b"old").unwrap();

        extract_zip_to_dir(&archive, &destination).unwrap();

        assert_eq!(fs::read(destination.join("fresh.bin")).unwrap(), b"fresh");
        assert!(!stage.exists());
        assert!(!previous.exists());
        assert!(!work.path().join(".install.oneirodex-ready-123-4").exists());
    }

    #[test]
    fn large_game_expanded_limit_override_accepts_positive_value() {
        assert_eq!(
            configured_archive_limit(Some("536870912000"), 200),
            536_870_912_000
        );
        assert_eq!(configured_archive_limit(Some("0"), 200), 200);
        assert_eq!(configured_archive_limit(Some("invalid"), 200), 200);
        assert_eq!(configured_archive_limit(None, 200), 200);
    }

    #[test]
    fn large_game_entry_limit_override_accepts_positive_value() {
        assert_eq!(configured_game_archive_entry_limit(Some("500000")), 500_000);
        assert_eq!(
            configured_game_archive_entry_limit(Some("0")),
            MAX_GAME_ARCHIVE_ENTRIES
        );
        assert_eq!(
            configured_game_archive_entry_limit(Some("invalid")),
            MAX_GAME_ARCHIVE_ENTRIES
        );
        assert_eq!(
            configured_game_archive_entry_limit(None),
            MAX_GAME_ARCHIVE_ENTRIES
        );
    }

    #[test]
    fn extraction_read_failure_keeps_existing_install_and_cleans_staging() {
        let work = tempdir().unwrap();
        let archive = work.path().join("corrupt.zip");
        write_zip(&archive, &[("game.bin", b"payload")]);
        let mut bytes = fs::read(&archive).unwrap();
        let name_length = u16::from_le_bytes([bytes[26], bytes[27]]) as usize;
        let extra_length = u16::from_le_bytes([bytes[28], bytes[29]]) as usize;
        let payload_start = 30 + name_length + extra_length;
        bytes[payload_start] ^= 0xff;
        fs::write(&archive, bytes).unwrap();

        let destination = work.path().join("install");
        fs::create_dir_all(&destination).unwrap();
        fs::write(destination.join("existing.bin"), b"keep me").unwrap();

        assert!(extract_zip_to_dir(&archive, &destination).is_err());
        assert_eq!(
            fs::read(destination.join("existing.bin")).unwrap(),
            b"keep me"
        );
        let abandoned_staging = fs::read_dir(work.path()).unwrap().any(|entry| {
            entry
                .ok()
                .and_then(|entry| entry.file_name().into_string().ok())
                .is_some_and(|name| name.starts_with(".install.staging-"))
        });
        assert!(
            !abandoned_staging,
            "failed extraction left a staging directory"
        );
    }

    #[test]
    fn filesystem_write_failure_keeps_existing_install_and_cleans_staging() {
        let work = tempdir().unwrap();
        let archive = work.path().join("conflicting-paths.zip");
        write_zip(
            &archive,
            &[("blocked", b"file"), ("blocked/child.bin", b"payload")],
        );
        let destination = work.path().join("install");
        fs::create_dir_all(&destination).unwrap();
        fs::write(destination.join("existing.bin"), b"keep me").unwrap();

        let error = extract_zip_to_dir(&archive, &destination).unwrap_err();

        assert!(
            !error.is_empty(),
            "filesystem entry conflict must fail extraction"
        );
        assert_eq!(
            fs::read(destination.join("existing.bin")).unwrap(),
            b"keep me"
        );
        assert_eq!(
            fs::read_dir(work.path())
                .unwrap()
                .filter_map(Result::ok)
                .filter(|entry| entry
                    .file_name()
                    .to_string_lossy()
                    .starts_with(".install.staging-"))
                .count(),
            0,
            "failed extraction must remove staging residue"
        );
    }

    #[test]
    #[ignore = "requires an owned small Linux tmpfs; run through the CI fixture"]
    fn real_disk_full_after_preflight_preserves_install_and_recovers() {
        assert_eq!(std::env::consts::OS, "linux", "Linux fixture required");
        assert_eq!(GAME_ARCHIVE_TEST_ENOSPC_AFTER.with(Cell::get), None);
        let root = PathBuf::from(std::env::var("ONEIRODEX_TEST_REAL_ENOSPC_ROOT").unwrap());
        let owner = std::env::var("ONEIRODEX_TEST_REAL_ENOSPC_OWNER").unwrap();
        assert!(!owner.is_empty() && owner.len() <= 128);
        assert!(root.is_absolute());
        assert_eq!(fs::canonicalize(&root).unwrap(), root);
        assert!(root
            .file_name()
            .unwrap()
            .to_string_lossy()
            .starts_with("oneirodex-enospc."));
        let metadata = fs::symlink_metadata(&root).unwrap();
        assert!(metadata.is_dir() && !metadata.file_type().is_symlink());
        assert!(Command::new("mountpoint")
            .arg("-q")
            .arg(&root)
            .status()
            .unwrap()
            .success());
        let filesystem = Command::new("stat")
            .args(["-f", "-c", "%T"])
            .arg(&root)
            .output()
            .unwrap();
        assert!(filesystem.status.success());
        assert_eq!(
            String::from_utf8(filesystem.stdout).unwrap().trim(),
            "tmpfs"
        );
        let capacity = fs2::total_space(&root).unwrap();
        assert!((8 * 1024 * 1024..=32 * 1024 * 1024).contains(&capacity));
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            let uid = Command::new("id").arg("-u").output().unwrap();
            assert!(uid.status.success());
            assert_eq!(
                metadata.uid(),
                String::from_utf8(uid.stdout)
                    .unwrap()
                    .trim()
                    .parse::<u32>()
                    .unwrap()
            );
            assert_eq!(metadata.mode() & 0o777, 0o700);
        }
        let marker = root.join(".oneirodex-enospc-owner");
        let marker_metadata = fs::symlink_metadata(&marker).unwrap();
        assert!(marker_metadata.is_file() && !marker_metadata.file_type().is_symlink());
        assert_eq!(fs::read_to_string(&marker).unwrap(), owner);
        let initial_entries: Vec<_> = fs::read_dir(&root).unwrap().map(Result::unwrap).collect();
        assert_eq!(initial_entries.len(), 1, "fixture must start empty");
        assert_eq!(initial_entries[0].path(), marker);

        let work = tempfile::tempdir_in(&root).unwrap();
        let archive = work.path().join("game.zip");
        let payload = vec![0x5a_u8; 4 * 1024 * 1024];
        write_zip(&archive, &[("game.bin", &payload)]);
        let destination = work.path().join("install");
        fs::create_dir(&destination).unwrap();
        fs::write(destination.join("game.bin"), b"old installed bytes").unwrap();
        let initial_available = available_space(work.path()).unwrap();
        assert!(initial_available > payload.len() as u64);
        let filler_path = work.path().join("owned-filler");
        let mut filler_bytes = 0_u64;
        let mut filler_errno = None;
        let mut staged_progress = 0_u64;
        let error = {
            let mut fill_after_partial_write = |bytes: u64, _total: u64| {
                if bytes == 0 || filler_errno.is_some() {
                    return;
                }
                let stage = fs::read_dir(work.path())
                    .unwrap()
                    .map(Result::unwrap)
                    .find(|entry| {
                        entry
                            .file_name()
                            .to_string_lossy()
                            .starts_with(".install.staging-")
                    })
                    .expect("partial staging directory must exist");
                staged_progress = fs::metadata(stage.path().join("game.bin")).unwrap().len();
                assert_eq!(staged_progress, bytes);
                let mut filler = File::create(&filler_path).unwrap();
                let chunk = [0xa5_u8; 64 * 1024];
                loop {
                    assert!(filler_bytes < 64 * 1024 * 1024, "bounded fixture overflow");
                    let remaining = (64 * 1024 * 1024 - filler_bytes).min(chunk.len() as u64);
                    match filler.write(&chunk[..remaining as usize]) {
                        Ok(0) => panic!("filler made no progress"),
                        Ok(written) => filler_bytes += written as u64,
                        Err(error) => {
                            filler_errno = error.raw_os_error();
                            assert_eq!(filler_errno, Some(28), "expected kernel ENOSPC");
                            break;
                        }
                    }
                }
            };
            let mut control = GameArchiveExtractionControl {
                cancellation: None,
                on_progress: &mut fill_after_partial_write,
            };
            extract_zip_to_dir_with_space_budget_and_control(
                &archive,
                &destination,
                10,
                8 * 1024 * 1024,
                0,
                None,
                &mut control,
            )
            .unwrap_err()
        };
        assert!(staged_progress > 0 && staged_progress < payload.len() as u64);
        assert!(filler_bytes > 0);
        assert_eq!(filler_errno, Some(28));
        assert!(error.contains("os error 28"), "got: {error}");
        assert_eq!(
            fs::read(destination.join("game.bin")).unwrap(),
            b"old installed bytes"
        );
        let residue_count = || {
            fs::read_dir(work.path())
                .unwrap()
                .map(Result::unwrap)
                .filter(|entry| {
                    let name = entry.file_name();
                    let name = name.to_string_lossy();
                    name.starts_with(".install.staging-")
                        || name.starts_with(".install.previous-")
                        || name.starts_with(".install.oneirodex-ready-")
                        || name.starts_with(".install.ready-pending-")
                })
                .count()
        };
        assert_eq!(
            residue_count(),
            0,
            "full-volume failure left recovery residue"
        );
        fs::remove_file(&filler_path).unwrap();
        extract_zip_to_dir_with_space_budget(&archive, &destination, 10, 8 * 1024 * 1024, 0, None)
            .unwrap();
        assert_eq!(fs::read(destination.join("game.bin")).unwrap(), payload);
        assert_eq!(residue_count(), 0);
        println!(
            "REAL_ENOSPC capacity={capacity} initial_available={initial_available} partial={staged_progress} filler={filler_bytes} errno=28 old_preserved=true stage_clean=true retry=true"
        );
    }

    #[test]
    fn simulated_disk_full_after_partial_write_preserves_existing_install() {
        let work = tempdir().unwrap();
        let archive = work.path().join("game.zip");
        write_zip(&archive, &[("game.bin", b"new game bytes")]);
        let destination = work.path().join("install");
        fs::create_dir_all(&destination).unwrap();
        fs::write(destination.join("game.bin"), b"old game bytes").unwrap();

        let _enospc = ArchiveEnospcGuard::after(3);
        let error = extract_zip_to_dir(&archive, &destination).unwrap_err();

        assert!(error.contains("simulated disk full"), "got: {error}");
        assert_eq!(
            fs::read(destination.join("game.bin")).unwrap(),
            b"old game bytes"
        );
        assert_eq!(
            fs::read_dir(work.path())
                .unwrap()
                .filter_map(Result::ok)
                .filter(|entry| entry
                    .file_name()
                    .to_string_lossy()
                    .starts_with(".install.staging-"))
                .count(),
            0,
            "ENOSPC failure must discard partial staging"
        );
    }

    #[test]
    fn extract_rejects_parent_traversal_before_replacing_destination() {
        let work = tempdir().unwrap();
        let archive = work.path().join("evil.zip");
        write_zip(
            &archive,
            &[("../escape.txt", b"pwned"), ("safe.txt", b"ok")],
        );
        let dest = work.path().join("out");
        fs::create_dir_all(&dest).unwrap();
        fs::write(dest.join("existing.bin"), b"keep me").unwrap();
        let error = extract_zip_to_dir(&archive, &dest).unwrap_err();
        assert!(error.contains("unsafe entry path"));

        // The traversal entry must not have been written anywhere outside dest.
        assert!(!work.path().join("escape.txt").exists());
        assert!(!dest.parent().unwrap().join("escape.txt").exists());
        // Validation fails before replacing a previous installation.
        assert_eq!(fs::read(dest.join("existing.bin")).unwrap(), b"keep me");
        assert!(!dest.join("safe.txt").exists());
        // And nothing escaped the destination at all.
        assert!(!dest.join("../escape.txt").exists());
    }

    #[test]
    fn extract_rejects_deep_traversal_and_absolute_entries_before_staging() {
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
        let error = extract_zip_to_dir(&archive, &dest).unwrap_err();
        assert!(error.contains("unsafe entry path"));

        assert!(!dest.exists());
        // Nothing may have been written outside the destination.
        assert!(!work.path().join("tmp").exists());
        assert!(!work.path().join("evil.bin").exists());
        assert!(!dest.parent().unwrap().join("tmp/evil.bin").exists());

        let abandoned_staging = fs::read_dir(work.path()).unwrap().any(|entry| {
            entry
                .ok()
                .and_then(|entry| entry.file_name().into_string().ok())
                .is_some_and(|name| name.starts_with(".out.staging-"))
        });
        assert!(
            !abandoned_staging,
            "unsafe archive left a staging directory"
        );
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

    #[cfg(unix)]
    #[test]
    fn staged_mod_zip_refuses_to_write_through_a_symlink_outside_install_root() {
        use std::os::unix::fs::symlink;

        let work = tempdir().unwrap();
        let install = work.path().join("installs/game");
        let outside = work.path().join("outside");
        fs::create_dir_all(&install).unwrap();
        fs::create_dir_all(&outside).unwrap();
        symlink(&outside, install.join("linked")).unwrap();

        let archive = work.path().join("mod.zip");
        write_zip(&archive, &[("linked/pwned.txt", b"outside")]);
        let file = fs::File::open(&archive).unwrap();
        let mut zip = ZipArchive::new(file).unwrap();

        let err = extract_staged_mod_zip(&mut zip, &install).unwrap_err();

        assert!(err.contains("escapes the install directory"), "got: {err}");
        assert!(!outside.join("pwned.txt").exists());
    }

    #[cfg(unix)]
    #[test]
    fn staged_mod_zip_refuses_to_create_a_dangling_symlink_target_outside_install_root() {
        use std::os::unix::fs::symlink;

        let work = tempdir().unwrap();
        let install = work.path().join("installs/game");
        let outside_target = work.path().join("outside/pwned.txt");
        fs::create_dir_all(&install).unwrap();
        fs::create_dir_all(outside_target.parent().unwrap()).unwrap();
        symlink(&outside_target, install.join("dangling.txt")).unwrap();

        let archive = work.path().join("mod.zip");
        write_zip(&archive, &[("dangling.txt", b"outside")]);
        let file = fs::File::open(&archive).unwrap();
        let mut zip = ZipArchive::new(file).unwrap();

        assert!(extract_staged_mod_zip(&mut zip, &install).is_err());
        assert!(!outside_target.exists());
    }

    #[test]
    fn staged_mod_zip_writes_nested_entries_inside_install_root() {
        let work = tempdir().unwrap();
        let install = work.path().join("installs/game");
        fs::create_dir_all(&install).unwrap();
        let archive = work.path().join("mod.zip");
        write_zip(&archive, &[("nested/mod.bin", b"payload")]);
        let file = fs::File::open(&archive).unwrap();
        let mut zip = ZipArchive::new(file).unwrap();

        assert_eq!(extract_staged_mod_zip(&mut zip, &install).unwrap(), (1, 7));
        assert_eq!(
            fs::read(install.join("nested/mod.bin")).unwrap(),
            b"payload"
        );
    }

    #[test]
    fn staged_mod_stats_enforces_entry_and_expanded_size_limits() {
        let work = tempdir().unwrap();
        let archive = work.path().join("mod.zip");
        write_zip(&archive, &[("one.bin", b"1234"), ("two.bin", b"5678")]);

        let entry_error = staged_mod_stats_with_limits(&archive, 1, 8).unwrap_err();
        assert!(entry_error.contains("1-entry limit"), "got: {entry_error}");
        let size_error = staged_mod_stats_with_limits(&archive, 2, 7).unwrap_err();
        assert!(
            size_error.contains("expanded-size limit"),
            "got: {size_error}"
        );

        let stats = staged_mod_stats_with_limits(&archive, 2, 8).unwrap();
        assert_eq!(stats.entry_count, 2);
        assert_eq!(stats.expanded_bytes, 8);
    }

    #[test]
    fn staged_mod_stats_refuses_unsupported_7z_archives() {
        let work = tempdir().unwrap();
        let archive = work.path().join("mod.7z");
        fs::write(&archive, b"not extracted").unwrap();
        let error = staged_mod_stats(&archive).unwrap_err();
        assert!(error.contains("7z mod archives are not supported"));
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
    fn containment_helpers_refuse_unc_and_device_strings_before_any_filesystem_probe() {
        // The same shapes the reveal check refuses, aimed at the helpers every
        // remove / write / extract / launch goes through. The exact refusal text
        // - not an OS error from a lookup, nor the generic "outside" message -
        // proves the text gate ran before `exists()`, which on Windows would
        // open an SMB connection to the named host.
        let base = tempdir().unwrap();
        let root = base.path().join("installs");
        fs::create_dir_all(&root).unwrap();
        for raw in [
            r"\\attacker.invalid\x",
            "//attacker.invalid/x",
            r"\\attacker.invalid\share\dir\file.txt",
            r"\/attacker.invalid\x",
            r"\\?\C:\Windows",
            r"\\?\UNC\attacker.invalid\x",
            r"\\.\pipe\x",
            r"\??\C:\Windows",
        ] {
            let path = Path::new(raw);
            assert_eq!(
                ensure_path_under_root(path, &root).unwrap_err(),
                PATH_NOT_PROBEABLE,
                "path: {raw}"
            );
            assert_eq!(
                ensure_path_strictly_under_root(path, &root).unwrap_err(),
                PATH_NOT_PROBEABLE,
                "strict path: {raw}"
            );
            assert_eq!(
                canonicalize_path(path, &root).unwrap_err(),
                PATH_NOT_PROBEABLE,
                "canonicalize: {raw}"
            );
            assert!(ensure_path_under_any_root(path, &[root.as_path()]).is_err());
            assert!(remove_path_within_roots(path, &[root.as_path()]).is_err());
        }
    }

    #[test]
    fn containment_helpers_refuse_a_relative_path_instead_of_resolving_it_against_the_working_directory(
    ) {
        // A root inside the working directory makes a relative path that lands
        // in it: without the text gate the lookup resolves it through the cwd
        // and the helper accepts a path nobody wrote as absolute.
        let base = tempfile::tempdir_in(std::env::current_dir().unwrap()).unwrap();
        let root = base.path().to_path_buf();
        let relative = Path::new(root.file_name().unwrap()).join("game.zip");
        assert!(!relative.is_absolute());
        assert_eq!(
            ensure_path_under_root(&relative, &root).unwrap_err(),
            PATH_NOT_PROBEABLE
        );
        assert_eq!(
            ensure_path_strictly_under_root(&relative, &root).unwrap_err(),
            PATH_NOT_PROBEABLE
        );
        assert!(ensure_path_under_any_root(&relative, &[root.as_path()]).is_err());
        // The same file by its absolute path is still fine.
        assert!(ensure_path_under_root(&root.join("game.zip"), &root).is_ok());
    }

    #[test]
    fn text_gate_lets_a_redirected_profiles_own_unc_folders_through_and_nothing_else() {
        // Windows Folder Redirection puts app data on a file server, which the OS
        // reports as a plain UNC path. Paths below that root are the app's own
        // folders; string compare only, so a host nobody named is still never
        // looked up.
        let root =
            Path::new(r"\\fs01\profiles$\chris\AppData\Roaming\com.oneirodex.desktop\installs");
        for path in [
            r"\\fs01\profiles$\chris\AppData\Roaming\com.oneirodex.desktop\installs",
            r"\\fs01\profiles$\chris\AppData\Roaming\com.oneirodex.desktop\installs\game\run.exe",
            "//FS01/profiles$/chris/AppData/Roaming/com.oneirodex.desktop/installs/game",
        ] {
            assert_eq!(
                check_path_text_before_probe(Path::new(path), root),
                Ok(()),
                "path: {path}"
            );
        }
        for path in [
            r"\\attacker\profiles$\chris\AppData\Roaming\com.oneirodex.desktop\installs\game",
            r"\\fs01\profiles$\other\AppData\Roaming\com.oneirodex.desktop\installs\game",
            r"\\fs01\profiles$\chris\AppData\Roaming\com.oneirodex.desktop\installs.evil\game",
            r"\\fs01\profiles$\chris\AppData\Roaming\com.oneirodex.desktop\installs\..\..\..\other",
            r"\\?\UNC\fs01\profiles$\chris\AppData\Roaming\com.oneirodex.desktop\installs\game",
            r"\\fs01\profiles$\chris",
        ] {
            assert_eq!(
                check_path_text_before_probe(Path::new(path), root).unwrap_err(),
                PATH_NOT_PROBEABLE,
                "path: {path}"
            );
        }
        // With an ordinary local root no UNC string is ever the app's own.
        assert!(check_path_text_before_probe(
            Path::new(r"\\fs01\profiles$\chris"),
            Path::new(r"C:\Users\chris\AppData\Roaming\app")
        )
        .is_err());
    }

    #[test]
    fn reveal_still_accepts_a_local_absolute_path() {
        let base = tempdir().unwrap();
        assert!(validate_reveal_path(base.path().to_str().unwrap()).is_ok());
    }

    // ---------------------------------------------------------------
    // macOS reveal arguments - a package is revealed, never opened
    // ---------------------------------------------------------------

    fn mac_args(target: &str, is_file: bool, select: bool) -> Vec<String> {
        macos_open_args(Path::new(target), is_file, select, |path| {
            path.to_path_buf()
        })
    }

    #[test]
    fn macos_selecting_always_reveals_and_never_opens() {
        for (target, is_file) in [
            ("/Users/me/games/Evil.app", false),
            ("/Users/me/games/Doom 3", false),
            ("/Users/me/games/Doom 3/base.pk4", true),
        ] {
            assert_eq!(mac_args(target, is_file, true), ["-R", target], "{target}");
        }
    }

    #[test]
    fn macos_opens_an_ordinary_folder_and_a_files_parent() {
        assert_eq!(
            mac_args("/Users/me/games/Doom 3", false, false),
            ["/Users/me/games/Doom 3"]
        );
        assert_eq!(
            mac_args("/Users/me/games/Doom 3/base.pk4", true, false),
            ["/Users/me/games/Doom 3"]
        );
        assert_eq!(mac_args("/", false, false), ["/"]);
        assert_eq!(mac_args("/file.bin", true, false), ["/"]);
    }

    #[test]
    fn macos_reveals_a_directory_named_like_a_package_instead_of_opening_it() {
        // `open Evil.app` would run the app. Every one of these is a directory
        // LaunchServices hands to a handler, so each is revealed (`-R`), not opened.
        for name in [
            "Evil.app",
            "Evil.APP",
            "Evil.bundle",
            "Evil.prefPane",
            "Evil.saver",
            "Evil.workflow",
            "Evil.scptd",
            "Evil.xpc",
            "Evil.appex",
            "Evil.kext",
            "Evil.plugin",
            "Evil.mpkg",
            "Evil.xcodeproj",
            "Evil.app.",
            ".hidden",
        ] {
            let dir = format!("/Users/me/installs/{name}");
            assert_eq!(mac_args(&dir, false, false), ["-R", dir.as_str()], "{name}");
            // A trailing separator does not hide the extension.
            let slashed = format!("{dir}/");
            assert_eq!(
                mac_args(&slashed, false, false),
                ["-R", slashed.as_str()],
                "{name}/"
            );
        }
    }

    #[test]
    fn macos_reveals_the_package_when_the_file_asked_for_sits_directly_inside_it() {
        // The open target of `Evil.app/Info.plist` is its parent, the bundle.
        assert_eq!(
            mac_args("/Users/me/installs/Evil.app/Info.plist", true, false),
            ["-R", "/Users/me/installs/Evil.app"]
        );
    }

    #[test]
    fn macos_resolves_symbolic_links_before_it_decides() {
        // installs/shortcut -> /Applications/Evil.app: the name is innocent, the
        // folder it opens is a package.
        let resolve = |path: &Path| {
            if path.ends_with("shortcut") {
                PathBuf::from("/Applications/Evil.app")
            } else {
                path.to_path_buf()
            }
        };
        assert_eq!(
            macos_open_args(
                Path::new("/Users/me/installs/shortcut"),
                false,
                false,
                resolve
            ),
            ["-R", "/Users/me/installs/shortcut"]
        );
        assert_eq!(
            macos_open_args(Path::new("/Users/me/installs/plain"), false, false, resolve),
            ["/Users/me/installs/plain"]
        );
    }

    // ---------------------------------------------------------------
    // Trusted network shares — a UNC path is probed only when the user (or the
    // OS, for the user's own folders) named its share. These call the
    // text-only gate: the real thing would open an SMB connection.
    // ---------------------------------------------------------------

    #[test]
    fn a_trusted_share_lets_its_paths_through_the_text_gate() {
        let trusted = vec![r"\\nas\roms".to_string()];
        for path in [
            r"\\nas\roms\Game",
            r"\\NAS\ROMS\Game\disc.cue",
            "//nas/roms/Game",
            r"\\nas\roms",
        ] {
            assert_eq!(
                check_reveal_path_text(path, &trusted),
                Ok(()),
                "path: {path}"
            );
        }
    }

    #[test]
    fn an_untrusted_host_or_share_is_still_refused_with_the_list_in_place() {
        let trusted = vec![r"\\nas\roms".to_string()];
        for path in [
            r"\\attacker\roms\Game",
            r"\\nas.evil.example\roms\Game",
            r"\\nas\other\Game",
            r"\\nas",
            r"\\?\UNC\nas\roms\Game",
            r"\\.\nas\roms",
            r"\??\UNC\nas\roms",
            r"//?/UNC/nas/roms",
        ] {
            assert_eq!(
                check_reveal_path_text(path, &trusted).unwrap_err(),
                NETWORK_PATH_REFUSED,
                "path: {path}"
            );
        }
        // No list, nothing trusted: the default is still refusal.
        assert_eq!(
            check_reveal_path_text(r"\\nas\roms\Game", &[]).unwrap_err(),
            NETWORK_PATH_REFUSED
        );
    }

    #[test]
    fn a_trusted_share_does_not_excuse_traversal_or_control_characters() {
        let trusted = vec![r"\\nas\roms".to_string()];
        // A `..` anywhere takes the path out of the trusted prefix altogether, so
        // it is refused as an untrusted network path rather than walked out of
        // the share.
        for path in [
            r"\\nas\roms\..\other",
            r"\\nas\roms\Game\..\..\other",
            r"\\nas\roms\.\Game",
        ] {
            assert_eq!(
                check_reveal_path_text(path, &trusted).unwrap_err(),
                NETWORK_PATH_REFUSED,
                "path: {path}"
            );
        }
        assert!(check_reveal_path_text("\\\\nas\\roms\\a\nb", &trusted)
            .unwrap_err()
            .contains("control"));
        assert_eq!(
            check_reveal_path_text(&format!(r"\\nas\roms\{}", "a".repeat(5000)), &trusted)
                .unwrap_err(),
            "Path is too long"
        );
    }

    #[test]
    fn only_os_reported_unc_roots_count_as_implicit_trust() {
        // `os_reported_share_roots` keeps a folder only when it is a plain UNC
        // path; a drive path or a verbatim form is never an implicit root.
        assert!(trusted_shares::is_plain_unc(
            r"\\fs01\profiles$\chris\Documents"
        ));
        assert!(!trusted_shares::is_plain_unc(r"C:\Users\chris\Documents"));
        assert!(!trusted_shares::is_plain_unc(r"\\?\UNC\fs01\profiles$"));
        let redirected = vec![r"\\fs01\profiles$\chris\Documents".to_string()];
        assert_eq!(
            check_reveal_path_text(
                r"\\fs01\profiles$\chris\Documents\My Games\Saves",
                &redirected
            ),
            Ok(())
        );
        assert!(check_reveal_path_text(r"\\fs01\profiles$\other\Documents", &redirected).is_err());
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
        // Verbatim UNC becomes the plain UNC form the OS reports for a redirected
        // profile; it is then refused at reveal unless its share is trusted.
        assert_eq!(
            user_facing_path(r"\\?\UNC\host\share\game"),
            r"\\host\share\game"
        );
        assert_eq!(user_facing_path(r"\\?\UNC\host\share"), r"\\host\share");
        // Device shapes, and a verbatim UNC with no host, are left alone.
        assert_eq!(user_facing_path(r"\\?\UNC\"), r"\\?\UNC\");
        assert_eq!(user_facing_path(r"\\?\UNC\\x"), r"\\?\UNC\\x");
        assert_eq!(user_facing_path(r"\\?\pipe"), r"\\?\pipe");
        assert_eq!(user_facing_path(r"\\.\pipe\x"), r"\\.\pipe\x");
    }

    // ---------------------------------------------------------------
    // validate_server_base_url — http:// only on the local network
    // ---------------------------------------------------------------

    /// The URL cases `src/transport-policy.test.ts` reads too: one JSON file, so
    /// the TypeScript check the UI runs and this backstop cannot drift apart.
    fn shared_url_cases() -> Vec<(String, bool)> {
        #[derive(Deserialize)]
        struct Case {
            url: String,
            ok: bool,
        }
        #[derive(Deserialize)]
        struct Fixture {
            cases: Vec<Case>,
        }
        let fixture: Fixture =
            serde_json::from_str(include_str!("../../fixtures/server-urls.json")).unwrap();
        fixture
            .cases
            .into_iter()
            .map(|case| (case.url, case.ok))
            .collect()
    }

    #[test]
    fn server_url_policy_matches_the_shared_fixture() {
        let cases = shared_url_cases();
        // A fixture that quietly emptied would pass vacuously.
        assert!(cases.len() > 50, "only {} cases", cases.len());
        assert!(cases.iter().any(|(_, ok)| *ok) && cases.iter().any(|(_, ok)| !*ok));
        for (url, expected) in &cases {
            match validate_server_base_url(url) {
                Ok(()) => assert!(*expected, "accepted, fixture says refuse: {url:?}"),
                Err(message) => {
                    assert!(
                        !*expected,
                        "refused, fixture says accept: {url:?}: {message}"
                    );
                    // Whatever the reason, the message points at the fix.
                    assert!(
                        message.contains("https://"),
                        "no https hint for {url:?}: {message}"
                    );
                }
            }
        }
    }

    #[test]
    fn server_url_blank_clears_the_saved_url() {
        // Not in the shared fixture: the TypeScript check refuses a blank URL.
        for url in ["", "   "] {
            assert!(validate_server_base_url(url).is_ok(), "rejected: {url:?}");
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

    // ---------------------------------------------------------------
    // InstallRecord - superseded generation survives a save/load round trip
    // ---------------------------------------------------------------

    #[test]
    fn install_record_keeps_the_superseded_generation_and_stays_compatible() {
        let legacy: InstallsFile = serde_json::from_str(
            r#"{"installs":{"g":{"archive_path":"a.zip","extract_path":"i/g","exe_path":null}}}"#,
        )
        .unwrap();
        let legacy_json = serde_json::to_string(&legacy).unwrap();
        assert!(!legacy_json.contains("superseded"), "{legacy_json}");

        let with_previous: InstallsFile = serde_json::from_str(
            r#"{"installs":{"g":{"archive_path":"new.zip","extract_path":"i/g-new","exe_path":null,
                "superseded":{"archive_path":"old.zip","extract_path":"i/g","retained_path":"i/g.uninstalled-1"}}}}"#,
        )
        .unwrap();
        let record = &with_previous.installs["g"];
        let previous = record.superseded.as_ref().expect("superseded is read");
        assert_eq!(previous.extract_path, "i/g");
        assert_eq!(previous.archive_path, "old.zip");
        assert_eq!(previous.retained_path.as_deref(), Some("i/g.uninstalled-1"));
        // Writing it back must not drop it - `save_installs` is a straight re-serialise.
        let round: InstallsFile =
            serde_json::from_str(&serde_json::to_string(&with_previous).unwrap()).unwrap();
        assert_eq!(
            round.installs["g"]
                .superseded
                .as_ref()
                .unwrap()
                .extract_path,
            "i/g"
        );
    }
}
