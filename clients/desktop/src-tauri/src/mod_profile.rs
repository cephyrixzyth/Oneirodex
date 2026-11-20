//! Per-install mod file ownership. A persisted before/after journal makes an interrupted
//! apply reversible; original files are retained outside the live install.
use serde::{de::DeserializeOwned, Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, File};
use std::io::{self, Read};
use std::path::{Component, Path, PathBuf};

#[derive(Default, Serialize, Deserialize)]
struct Profile {
    id: String,
    files: BTreeMap<PathBuf, OwnedFile>,
}
#[derive(Serialize, Deserialize)]
struct OwnedFile {
    original: Option<String>,
    applied: String,
}
#[derive(Serialize, Deserialize)]
struct Journal {
    id: String,
    changes: Vec<Change>,
}
#[derive(Serialize, Deserialize)]
struct Change {
    path: PathBuf,
    before: Option<String>,
    after: Option<String>,
}

fn err(e: impl std::fmt::Display) -> String {
    e.to_string()
}

fn read_json<T: DeserializeOwned>(path: &Path) -> Result<Option<T>, String> {
    match fs::read(path) {
        Ok(raw) => serde_json::from_slice(&raw).map(Some).map_err(err),
        Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(None),
        Err(e) => Err(err(e)),
    }
}

fn write_json(path: &Path, value: &impl Serialize) -> Result<(), String> {
    super::install_recovery::atomic_write(path, &serde_json::to_vec(value).map_err(err)?)
        .map_err(err)
}

fn hex(digest: impl AsRef<[u8]>) -> String {
    digest.as_ref().iter().map(|b| format!("{b:02x}")).collect()
}

fn digest_file(path: &Path) -> Result<Option<String>, String> {
    let mut file = match File::open(path) {
        Ok(file) => file,
        Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(None),
        Err(e) => return Err(err(e)),
    };
    let mut hash = Sha256::new();
    let mut buf = [0u8; 65536];
    loop {
        let n = file.read(&mut buf).map_err(err)?;
        if n == 0 {
            break;
        }
        hash.update(&buf[..n]);
    }
    Ok(Some(hex(hash.finalize())))
}

fn target(root: &Path, relative: &Path) -> Result<PathBuf, String> {
    let mut path = root.to_path_buf();
    if relative.as_os_str().is_empty() {
        return Err("Empty mod path".into());
    }
    for part in relative.components() {
        let Component::Normal(name) = part else {
            return Err("Invalid mod path".into());
        };
        path.push(name);
        match fs::symlink_metadata(&path) {
            Ok(meta) if meta.file_type().is_symlink() => {
                return Err(format!("Linked mod destination: {}", relative.display()))
            }
            Ok(_) => {}
            Err(e) if e.kind() == io::ErrorKind::NotFound => {}
            Err(e) => return Err(err(e)),
        }
    }
    Ok(path)
}

fn object(objects: &Path, hash: &str) -> Result<PathBuf, String> {
    if hash.len() != 64 || !hash.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err("Invalid backup identity".into());
    }
    Ok(objects.join(hash))
}

// Copy on the destination filesystem and rename only after a complete, verified copy.
fn publish(source: &Path, dest: &Path, hash: &str) -> Result<(), String> {
    let parent = dest.parent().ok_or("Invalid destination")?;
    fs::create_dir_all(parent).map_err(err)?;
    let temp = parent.join(format!(".oneirodex-pending-{}", uuid::Uuid::new_v4()));
    let result = (|| {
        fs::copy(source, &temp).map_err(err)?;
        // Windows flushes only through a handle with write access.
        fs::OpenOptions::new()
            .write(true)
            .open(&temp)
            .and_then(|f| f.sync_all())
            .map_err(err)?;
        if digest_file(&temp)?.as_deref() != Some(hash) {
            return Err("File changed while preparing the mod profile".into());
        }
        fs::rename(&temp, dest).map_err(err)
    })();
    if result.is_err() {
        let _ = fs::remove_file(temp);
    }
    result
}

fn retain(objects: &Path, src: &Path) -> Result<Option<String>, String> {
    let hash = digest_file(src)?;
    if let Some(ref h) = hash {
        let dest = object(objects, h)?;
        if !dest.exists() {
            publish(src, &dest, h)?;
        }
    }
    Ok(hash)
}

fn set_file(objects: &Path, dest: &Path, hash: Option<&str>) -> Result<(), String> {
    match hash {
        Some(h) => publish(&object(objects, h)?, dest, h),
        None => fs::remove_file(dest).map_err(err),
    }
}

fn change(root: &Path, objects: &Path, item: &Change, forward: bool) -> Result<(), String> {
    let dest = target(root, &item.path)?;
    let (from, to) = if forward {
        (&item.before, &item.after)
    } else {
        (&item.after, &item.before)
    };
    let current = digest_file(&dest)?;
    if &current == to {
        return Ok(());
    }
    if &current != from {
        return Err(format!(
            "{} was edited. Preserve your changes before retrying.",
            item.path.display()
        ));
    }
    set_file(objects, &dest, to.as_deref())
}

fn recover(root: &Path, state: &Path, profile: &Profile) -> Result<(), String> {
    let journal_path = state.join("journal.json");
    let Some(journal): Option<Journal> = read_json(&journal_path)? else {
        return Ok(());
    };
    if journal.id != profile.id {
        for item in journal.changes.iter().rev() {
            change(root, &state.join("objects"), item, false)?;
        }
    }
    fs::remove_file(journal_path).map_err(err)
}

fn files(root: &Path, dir: &Path, results: &mut BTreeSet<PathBuf>) -> Result<(), String> {
    for node in fs::read_dir(dir).map_err(err)? {
        let entry = node.map_err(err)?;
        let path = entry.path();
        let kind = entry.file_type().map_err(err)?;
        if kind.is_dir() {
            files(root, &path, results)?;
        } else if kind.is_file() {
            results.insert(path.strip_prefix(root).map_err(err)?.to_owned());
        } else {
            return Err("Unsupported mod file type".into());
        }
    }
    Ok(())
}

pub fn recover_before_launch(root: &Path, state: &Path) -> Result<(), String> {
    if !state.join("journal.json").try_exists().map_err(err)? {
        return Ok(());
    }
    let profile = read_json(&state.join("active.json"))?.unwrap_or_default();
    recover(root, state, &profile)
}

pub fn apply(root: &Path, state: &Path, sources: &[PathBuf]) -> Result<u32, String> {
    let result = apply_profile(root, state, sources);
    // A failed preflight can also leave large provisional objects. Keep everything when
    // recovery is pending or ownership metadata is unreadable.
    if matches!(state.join("journal.json").try_exists(), Ok(false)) {
        if let Ok(profile) = read_json::<Profile>(&state.join("active.json")) {
            let active = profile.unwrap_or_default();
            let keep: BTreeSet<_> = active
                .files
                .values()
                .filter_map(|row| row.original.as_deref())
                .collect();
            if let Ok(entries) = fs::read_dir(state.join("objects")) {
                for entry in entries.flatten() {
                    if !keep.contains(entry.file_name().to_string_lossy().as_ref()) {
                        let _ = fs::remove_file(entry.path());
                    }
                }
            }
        }
    }
    result
}

fn apply_profile(root: &Path, state: &Path, sources: &[PathBuf]) -> Result<u32, String> {
    let objects = state.join("objects");
    fs::create_dir_all(&objects).map_err(err)?;
    let active_path = state.join("active.json");
    let active: Profile = read_json(&active_path)?.unwrap_or_default();
    recover(root, state, &active)?;
    let id = uuid::Uuid::new_v4().to_string();
    let overlay = state.join(format!("stage-{id}"));
    fs::create_dir(&overlay).map_err(err)?;
    let _cleanup = super::DirectoryCleanup(overlay.clone());
    let mut total_bytes = 0u64;
    let mut total_entries = 0u64;
    for source in sources {
        let stats = super::staged_mod_stats_with_limits(
            source,
            super::MAX_MOD_ARCHIVE_ENTRIES - total_entries,
            super::MAX_MOD_ARCHIVE_EXPANDED_BYTES - total_bytes,
        )?;
        total_entries += stats.entry_count;
        if super::is_mod_zip_path(source) {
            let mut zip = zip::ZipArchive::new(File::open(source).map_err(err)?).map_err(err)?;
            total_bytes += super::extract_staged_mod_zip(&mut zip, &overlay)?.1;
        } else {
            let name = source
                .file_name()
                .and_then(|n| n.to_str())
                .ok_or("Invalid mod file name")?;
            total_bytes +=
                fs::copy(source, overlay.join(super::sanitize_mod_filename(name))).map_err(err)?;
        }
        if total_bytes > super::MAX_MOD_ARCHIVE_EXPANDED_BYTES {
            return Err("Mod pack exceeds the expanded-size limit".into());
        }
    }
    let mut paths = BTreeSet::new();
    files(&overlay, &overlay, &mut paths)?;
    let applied_count = paths.len() as u32;
    paths.extend(active.files.keys().cloned());
    #[cfg(any(windows, target_os = "macos"))]
    {
        let mut folded = BTreeSet::new();
        for name in &paths {
            if !folded.insert(name.to_string_lossy().to_lowercase()) {
                return Err(format!(
                    "Mod paths differ only by case: {}. Use the same spelling across profiles.",
                    name.display()
                ));
            }
        }
    }
    let mut next = Profile {
        id: id.clone(),
        ..Profile::default()
    };
    let mut journal = Journal {
        id,
        changes: Vec::new(),
    };
    for path in paths {
        let live = target(root, &path)?;
        let before = retain(&objects, &live)?;
        let original = if let Some(old) = active.files.get(&path) {
            if before.as_ref() != Some(&old.applied) && before != old.original {
                return Err(format!("{} changed since the last mod apply. Preserve local edits before switching profiles.", path.display()));
            }
            old.original.clone()
        } else {
            before.clone()
        };
        let staged = retain(&objects, &overlay.join(&path))?;
        let after = if let Some(hash) = staged {
            next.files.insert(
                path.clone(),
                OwnedFile {
                    original,
                    applied: hash.clone(),
                },
            );
            Some(hash)
        } else {
            original
        };
        if before != after {
            journal.changes.push(Change {
                path,
                before,
                after,
            });
        }
    }
    let journal_path = state.join("journal.json");
    write_json(&journal_path, &journal)?;
    let update = (|| {
        for item in &journal.changes {
            change(root, &objects, item, true)?;
        }
        write_json(&active_path, &next)
    })();
    if let Err(e) = update {
        recover(root, state, &active)
            .map_err(|rollback| format!("{e}. Recovery pending: {rollback}"))?;
        return Err(e);
    }
    fs::remove_file(journal_path).map_err(err)?;
    Ok(applied_count)
}

/// Build an update from the new archive and personal files. An enabled mod from the previous
/// installation must not silently become an unowned part of the new base.
pub fn retain_for_update(
    source: &Path,
    destination: &Path,
    state: &Path,
) -> Result<super::install_recovery::RetainSummary, String> {
    let active: Profile = read_json(&state.join("active.json"))?.unwrap_or_default();
    recover(source, state, &active)?;
    let mut excluded = BTreeSet::new();
    for (relative, row) in &active.files {
        let from = target(source, relative)?;
        if digest_file(&from)?.as_ref() != Some(&row.applied) {
            continue; // A local edit follows the existing personal-file retention rule.
        }
        excluded.insert(from);
        if let Some(original) = &row.original {
            let dest = target(destination, relative)?;
            if !dest.try_exists().map_err(err)? {
                publish(&object(&state.join("objects"), original)?, &dest, original)?;
            }
        }
    }
    super::install_recovery::retain_missing_except(source, destination, &excluded).map_err(err)
}

pub fn state_path(app_data: &Path, root: &Path) -> PathBuf {
    app_data
        .join("applied-mod-profiles")
        .join(hex(Sha256::digest(root.as_os_str().as_encoded_bytes())))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn switching_profiles_restores_original_and_protects_edits() {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path().join("install");
        let state = temp.path().join("state");
        let a = temp.path().join("a.bin");
        let b = temp.path().join("b.bin");
        fs::create_dir(&root).unwrap();
        fs::write(root.join("a.bin"), b"original").unwrap();
        fs::write(&a, b"mod-a").unwrap();
        fs::write(&b, b"mod-b").unwrap();
        apply(&root, &state, &[a.clone(), b.clone()]).unwrap();
        assert_eq!(fs::read(root.join("a.bin")).unwrap(), b"mod-a");
        apply(&root, &state, std::slice::from_ref(&b)).unwrap();
        assert_eq!(fs::read(root.join("a.bin")).unwrap(), b"original");
        let previous_objects = fs::read_dir(state.join("objects")).unwrap().count();
        fs::write(root.join("b.bin"), b"manual edit").unwrap();
        assert!(apply(&root, &state, &[]).unwrap_err().contains("changed"));
        assert_eq!(fs::read(root.join("b.bin")).unwrap(), b"manual edit");
        assert_eq!(
            fs::read_dir(state.join("objects")).unwrap().count(),
            previous_objects
        );
        fs::write(root.join("b.bin"), b"mod-b").unwrap();
        apply(&root, &state, &[]).unwrap();
        assert!(!root.join("b.bin").exists());
    }

    #[test]
    fn interrupted_file_commit_recovers_before_next_apply() {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path().join("install");
        let state = temp.path().join("state");
        let objects = state.join("objects");
        fs::create_dir_all(&objects).unwrap();
        fs::create_dir(&root).unwrap();
        let file = root.join("a.bin");
        fs::write(&file, b"before").unwrap();
        let before = retain(&objects, &file).unwrap();
        fs::write(&file, b"after").unwrap();
        let after = digest_file(&file).unwrap();
        write_json(
            &state.join("journal.json"),
            &Journal {
                id: "incomplete".into(),
                changes: vec![Change {
                    path: "a.bin".into(),
                    before,
                    after,
                }],
            },
        )
        .unwrap();
        apply(&root, &state, &[]).unwrap();
        assert_eq!(fs::read(file).unwrap(), b"before");
    }

    #[test]
    fn update_generation_retains_personal_files_and_leaves_managed_mods_behind() {
        let temp = tempfile::tempdir().unwrap();
        let source = temp.path().join("old");
        let destination = temp.path().join("new");
        let state = temp.path().join("profile");
        fs::create_dir(&source).unwrap();
        fs::create_dir(&destination).unwrap();
        fs::write(source.join("config.ini"), b"original").unwrap();
        fs::write(source.join("save.dat"), b"personal").unwrap();
        let config = temp.path().join("config.ini");
        let extra = temp.path().join("mod.dat");
        fs::write(&config, b"pack").unwrap();
        fs::write(&extra, b"extra").unwrap();
        apply(&source, &state, &[config, extra]).unwrap();
        retain_for_update(&source, &destination, &state).unwrap();
        assert_eq!(
            fs::read(destination.join("config.ini")).unwrap(),
            b"original"
        );
        assert_eq!(fs::read(destination.join("save.dat")).unwrap(), b"personal");
        assert!(!destination.join("mod.dat").exists());
        assert_eq!(fs::read(source.join("mod.dat")).unwrap(), b"extra");
    }
}
