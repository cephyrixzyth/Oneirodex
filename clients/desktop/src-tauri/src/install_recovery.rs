//! Update generations leave the working files intact; registry rename commits selection.
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};

static NEXT_WRITE: AtomicU64 = AtomicU64::new(0);

pub fn atomic_write(path: &Path, bytes: &[u8]) -> std::io::Result<()> {
    let temp = path.with_extension(format!(
        "pending-{}-{}",
        std::process::id(),
        NEXT_WRITE.fetch_add(1, Ordering::Relaxed)
    ));
    let result = (|| {
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temp)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        drop(file);
        fs::rename(&temp, path)
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temp);
    }
    result
}

/// Copy missing files only. Existing archive entries win; original files stay intact.
pub fn retain_missing(from: &Path, to: &Path) -> std::io::Result<()> {
    if fs::symlink_metadata(from)?.file_type().is_symlink()
        || fs::symlink_metadata(to)?.file_type().is_symlink()
    {
        return Err(std::io::Error::other(
            "Linked install directories cannot be copied",
        ));
    }
    for entry in fs::read_dir(from)? {
        let entry = entry?;
        let source = entry.path();
        let target = to.join(entry.file_name());
        let kind = entry.file_type()?;
        if kind.is_symlink() {
            return Err(std::io::Error::other(
                "Linked install files cannot be copied",
            ));
        }
        if let Ok(metadata) = fs::symlink_metadata(&target) {
            if metadata.file_type().is_symlink() {
                return Err(std::io::Error::other(
                    "Linked update files cannot be copied",
                ));
            }
            if kind.is_dir() && target.is_dir() {
                retain_missing(&source, &target)?;
            }
        } else if kind.is_dir() {
            fs::create_dir(&target)?;
            retain_missing(&source, &target)?;
        } else if kind.is_file() {
            fs::copy(&source, &target)?;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn scratch() -> std::path::PathBuf {
        let path = std::env::temp_dir().join(format!(
            "oneirodex-recovery-{}-{}",
            std::process::id(),
            NEXT_WRITE.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        path
    }
    #[test]
    fn registry_replacement_is_readable_after_restart() {
        let root = scratch();
        let path = root.join("installs.json");
        atomic_write(&path, b"old").unwrap();
        atomic_write(&path, b"new").unwrap();
        assert_eq!(fs::read(&path).unwrap(), b"new");
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn failed_rename_leaves_destination_intact() {
        let root = scratch();
        let path = root.join("occupied");
        fs::create_dir(&path).unwrap();
        fs::write(path.join("old"), b"working").unwrap();
        assert!(atomic_write(&path, b"new").is_err());
        assert_eq!(fs::read(path.join("old")).unwrap(), b"working");
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn interrupted_write_does_not_change_selected_generation() {
        let root = scratch();
        let path = root.join("installs.json");
        atomic_write(&path, b"old").unwrap();
        fs::write(root.join("installs.pending-crash"), b"partial").unwrap();
        assert_eq!(fs::read(&path).unwrap(), b"old");
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn update_keeps_saves_and_base_files_without_overwriting_new_files() {
        let root = scratch();
        let old = root.join("old");
        let new = root.join("new");
        fs::create_dir_all(old.join("saves")).unwrap();
        fs::create_dir(&new).unwrap();
        fs::write(old.join("saves/slot"), b"progress").unwrap();
        fs::write(old.join("game"), b"old-version").unwrap();
        fs::write(new.join("game"), b"new-version").unwrap();
        retain_missing(&old, &new).unwrap();
        assert_eq!(fs::read(new.join("saves/slot")).unwrap(), b"progress");
        assert_eq!(fs::read(new.join("game")).unwrap(), b"new-version");
        assert_eq!(fs::read(old.join("game")).unwrap(), b"old-version");
        fs::remove_dir_all(root).unwrap();
    }
}
