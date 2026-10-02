//! Update generations leave the working files intact; registry rename commits selection.
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
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

/// What `retain_missing` left out, so a caller can say so instead of pretending
/// the copy was byte-for-byte.
#[derive(Debug, Default, PartialEq, Eq)]
pub struct RetainSummary {
    /// Symbolic links and junctions that were not copied.
    pub skipped_links: Vec<PathBuf>,
}

/// Copy missing files only. Existing archive entries win; original files stay intact.
///
/// Symbolic links and Windows junctions are never followed and never copied. A
/// link is not the user's data: it points at data that lives elsewhere (a save
/// folder on another drive, a Wine prefix's `dosdevices/z:` that points at `/`),
/// and following one would copy whatever it names into the snapshot. Failing the
/// whole copy instead left such an install impossible to update, and — before
/// uninstall stopped snapshotting by default — impossible to remove. The skipped
/// links are reported; the data they point at is left exactly where it is.
pub fn retain_missing(from: &Path, to: &Path) -> std::io::Result<RetainSummary> {
    if fs::symlink_metadata(from)?.file_type().is_symlink()
        || fs::symlink_metadata(to)?.file_type().is_symlink()
    {
        return Err(std::io::Error::other(
            "Linked install directories cannot be copied",
        ));
    }
    let mut summary = RetainSummary::default();
    retain_entries(from, to, &mut summary)?;
    Ok(summary)
}

fn retain_entries(from: &Path, to: &Path, summary: &mut RetainSummary) -> std::io::Result<()> {
    for entry in fs::read_dir(from)? {
        let entry = entry?;
        let source = entry.path();
        let target = to.join(entry.file_name());
        let kind = entry.file_type()?;
        if kind.is_symlink() {
            summary.skipped_links.push(source);
            continue;
        }
        if let Ok(metadata) = fs::symlink_metadata(&target) {
            if metadata.file_type().is_symlink() {
                // Never write through a link that is already in the destination.
                summary.skipped_links.push(target);
                continue;
            }
            if kind.is_dir() && target.is_dir() {
                retain_entries(&source, &target, summary)?;
            }
        } else if kind.is_dir() {
            fs::create_dir(&target)?;
            retain_entries(&source, &target, summary)?;
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
    /// A directory link (symlink on unix, junction on Windows — a junction needs
    /// no privilege, a Windows symlink does). `true` when it was created.
    fn make_dir_link(link: &Path, target: &Path) -> bool {
        #[cfg(unix)]
        {
            std::os::unix::fs::symlink(target, link).is_ok()
        }
        #[cfg(windows)]
        {
            std::process::Command::new("cmd")
                .args(["/C", "mklink", "/J"])
                .arg(link)
                .arg(target)
                .output()
                .map(|output| output.status.success())
                .unwrap_or(false)
        }
        #[cfg(not(any(unix, windows)))]
        {
            let _ = (link, target);
            false
        }
    }
    #[test]
    fn links_are_skipped_not_followed_and_do_not_fail_the_copy() {
        let root = scratch();
        let outside = root.join("outside-saves");
        let old = root.join("old");
        let new = root.join("new");
        fs::create_dir(&outside).unwrap();
        fs::write(outside.join("slot"), b"elsewhere").unwrap();
        fs::create_dir_all(old.join("data")).unwrap();
        fs::create_dir(&new).unwrap();
        fs::write(old.join("game"), b"exe").unwrap();
        fs::write(old.join("data/file"), b"kept").unwrap();
        assert!(
            make_dir_link(&old.join("saves"), &outside),
            "could not create a directory link for the test"
        );

        let summary = retain_missing(&old, &new).expect("a link must not fail the copy");

        assert_eq!(fs::read(new.join("game")).unwrap(), b"exe");
        assert_eq!(fs::read(new.join("data/file")).unwrap(), b"kept");
        // Neither the link nor what it points at was copied in.
        assert!(fs::symlink_metadata(new.join("saves")).is_err());
        assert_eq!(summary.skipped_links, vec![old.join("saves")]);
        // What the link points at is untouched.
        assert_eq!(fs::read(outside.join("slot")).unwrap(), b"elsewhere");
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn a_link_already_in_the_destination_is_not_written_through() {
        let root = scratch();
        let elsewhere = root.join("elsewhere");
        let old = root.join("old");
        let new = root.join("new");
        fs::create_dir(&elsewhere).unwrap();
        fs::create_dir_all(old.join("dir")).unwrap();
        fs::create_dir(&new).unwrap();
        fs::write(old.join("dir/file"), b"data").unwrap();
        assert!(
            make_dir_link(&new.join("dir"), &elsewhere),
            "could not create a directory link for the test"
        );

        let summary = retain_missing(&old, &new).expect("a link must not fail the copy");

        assert!(!elsewhere.join("file").exists());
        assert_eq!(summary.skipped_links, vec![new.join("dir")]);
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn a_linked_root_is_still_refused() {
        let root = scratch();
        let real = root.join("real");
        let new = root.join("new");
        fs::create_dir(&real).unwrap();
        fs::create_dir(&new).unwrap();
        let linked = root.join("linked");
        assert!(
            make_dir_link(&linked, &real),
            "could not create a directory link for the test"
        );
        assert!(retain_missing(&linked, &new).is_err());
        assert!(retain_missing(&real, &linked).is_err());
        fs::remove_dir_all(root).unwrap();
    }
}
