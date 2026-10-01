//! Network shares the user has told the companion to trust for "open path".
//!
//! A queued `open_path` is written by the server, and on Windows merely probing a
//! UNC path (`Path::exists`) makes the OS open an SMB connection and answer the
//! named host's NTLM challenge, handing it the user's credential hash. So a UNC
//! path is refused by default. A Windows-hosted server is told to use UNC library
//! roots (`ONEIRODEX_LIBRARY_ROOTS=NAS ROMs=\\nas\roms`), though, and the server
//! cannot say which of those the companion's owner trusts — so the owner says so,
//! here, on this PC.
//!
//! Everything in this module is string work. Nothing touches the filesystem: the
//! decision "may this path be probed at all" has to be made before any probe.

use std::path::Path;

/// More than this is a typo or a paste accident, not a household.
pub const MAX_TRUSTED_SHARES: usize = 32;

const MAX_ROOT_LEN: usize = 1024;

fn is_separator(c: char) -> bool {
    c == '/' || c == '\\'
}

/// `\\host\share\a\b` as `["host", "share", "a", "b"]`.
///
/// Only the plain two-separator form qualifies. Win32 device and verbatim
/// namespaces (`\\?\`, `\\.\`), the NT object prefix (`\??\`) and a third
/// leading separator return `None`, as do an empty host and `.` / `..` segments,
/// so the segment list means the same thing to this code as it does to Windows.
/// Runs of separators collapse the way Windows collapses them.
fn unc_segments(path: &str) -> Option<Vec<&str>> {
    let mut chars = path.chars();
    if !(chars.next().is_some_and(is_separator) && chars.next().is_some_and(is_separator)) {
        return None;
    }
    let rest = &path[2..];
    if rest.chars().next().is_some_and(is_separator) {
        return None;
    }
    let segments: Vec<&str> = rest.split(is_separator).filter(|s| !s.is_empty()).collect();
    let host = *segments.first()?;
    if host == "?" || host == "." {
        return None;
    }
    if segments.iter().any(|s| *s == "." || *s == "..") {
        return None;
    }
    Some(segments)
}

/// Is `path` a plain UNC path (`\\host\...`)? Used for the implicit roots the OS
/// reports for the user's own folders.
pub fn is_plain_unc(path: &str) -> bool {
    unc_segments(path.trim()).is_some()
}

/// Validate one entry the user typed and return its canonical `\\host\share\...`
/// form (backslashes, original case, no trailing separator).
pub fn normalize_share_root(raw: &str) -> Result<String, String> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return Err("A trusted network share cannot be empty".into());
    }
    let example = r"Use the form \\server\share, for example \\nas\roms";
    if trimmed.len() > MAX_ROOT_LEN {
        return Err(format!("Trusted network share is too long. {example}"));
    }
    if trimmed.chars().any(char::is_control) {
        return Err("Trusted network share contains invalid control characters".into());
    }
    let Some(segments) = unc_segments(trimmed) else {
        return Err(format!(
            "{trimmed} is not a network share path. {example}. Device paths (\\\\?\\, \\\\.\\) and paths with . or .. segments are never trusted"
        ));
    };
    if segments.len() < 2 {
        return Err(format!("{trimmed} names a server but no share. {example}"));
    }
    if segments
        .iter()
        .any(|s| s.contains(['<', '>', '"', '|', '?', '*']))
    {
        return Err(format!(
            "{trimmed} contains a character that cannot appear in a share path. {example}"
        ));
    }
    Ok(format!(r"\\{}", segments.join(r"\")))
}

/// Normalize a whole list: validate each entry, drop exact repeats, cap the size.
pub fn normalize_share_roots(raw: &[String]) -> Result<Vec<String>, String> {
    let mut out: Vec<String> = Vec::new();
    for entry in raw {
        if entry.trim().is_empty() {
            continue;
        }
        let normalized = normalize_share_root(entry)?;
        let key = normalized.to_ascii_lowercase();
        if !out.iter().any(|seen| seen.to_ascii_lowercase() == key) {
            out.push(normalized);
        }
    }
    if out.len() > MAX_TRUSTED_SHARES {
        return Err(format!(
            "At most {MAX_TRUSTED_SHARES} trusted network shares are supported"
        ));
    }
    Ok(out)
}

/// Is `path` a UNC path at or below one of `roots`?
///
/// Compared segment by segment, ASCII-case-insensitively. ASCII only on purpose:
/// full Unicode lowercasing would equate a look-alike host with a trusted one
/// (the Kelvin sign lowercases to `k`) and hand the NTLM hash to the wrong
/// machine, while an exact or ASCII-case match can only ever name the same host.
/// A path that differs from a root in any other way — a trailing dot, a `..`, a
/// different share — is not under it. Never touches the filesystem.
pub fn is_under_trusted_share<S: AsRef<str>>(path: &str, roots: &[S]) -> bool {
    let Some(candidate) = unc_segments(path.trim()) else {
        return false;
    };
    roots.iter().any(|root| {
        let Some(root) = unc_segments(root.as_ref().trim()) else {
            return false;
        };
        root.len() >= 2
            && candidate.len() >= root.len()
            && root
                .iter()
                .zip(candidate.iter())
                .all(|(wanted, got)| wanted.eq_ignore_ascii_case(got))
    })
}

/// The persisted list. Any read problem — no file yet, unreadable, not JSON — is
/// an empty list, and an entry that would not pass `normalize_share_root` is
/// dropped, so a hand-edited file can only ever trust less, never more.
pub fn read_share_roots(file: &Path) -> Vec<String> {
    #[derive(serde::Deserialize)]
    struct Stored {
        #[serde(default)]
        roots: Vec<String>,
    }
    let Ok(data) = std::fs::read_to_string(file) else {
        return Vec::new();
    };
    let Ok(stored) = serde_json::from_str::<Stored>(&data) else {
        return Vec::new();
    };
    stored
        .roots
        .iter()
        .filter_map(|root| normalize_share_root(root).ok())
        .take(MAX_TRUSTED_SHARES)
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalizes_a_share_and_keeps_its_case() {
        assert_eq!(normalize_share_root(r"\\NAS\ROMs").unwrap(), r"\\NAS\ROMs");
        assert_eq!(normalize_share_root("//nas/roms/").unwrap(), r"\\nas\roms");
        assert_eq!(
            normalize_share_root(r"  \\nas\\roms\Retro\  ").unwrap(),
            r"\\nas\roms\Retro"
        );
        assert_eq!(normalize_share_root(r"\\nas\c$").unwrap(), r"\\nas\c$");
    }

    #[test]
    fn refuses_entries_that_are_not_a_plain_share() {
        for entry in [
            "",
            "   ",
            r"C:\Games",
            "/mnt/user/games",
            r"\nas\roms",
            r"\\nas",
            r"\\nas\",
            r"\\\nas\roms",
            r"\\?\UNC\nas\roms",
            r"\\?\C:\Windows",
            r"\\.\pipe\x",
            r"\??\C:\Windows",
            r"\\nas\roms\..\other",
            r"\\nas\.\roms",
            r"\\nas\ro*ms",
            r"\\nas\ro?ms",
            "\\\\nas\\roms\0",
            "\\\\nas\\roms\nx",
        ] {
            assert!(normalize_share_root(entry).is_err(), "accepted: {entry:?}");
        }
        assert!(normalize_share_root(&format!(r"\\nas\{}", "a".repeat(2000))).is_err());
    }

    #[test]
    fn list_normalization_drops_blanks_and_repeats_and_caps_the_size() {
        let list = normalize_share_roots(&[
            r"\\nas\roms".into(),
            "".into(),
            r"\\NAS\ROMS\".into(),
            r"\\nas\archive".into(),
        ])
        .unwrap();
        assert_eq!(list, vec![r"\\nas\roms", r"\\nas\archive"]);
        // One bad entry fails the whole save instead of being silently dropped.
        assert!(normalize_share_roots(&[r"\\nas\roms".into(), "C:\\x".into()]).is_err());
        let many: Vec<String> = (0..=MAX_TRUSTED_SHARES)
            .map(|i| format!(r"\\nas\share{i}"))
            .collect();
        assert!(normalize_share_roots(&many).is_err());
    }

    #[test]
    fn a_path_is_trusted_only_at_or_below_a_listed_share() {
        let roots = [
            r"\\nas\roms".to_string(),
            r"\\other\Archive\Retro".to_string(),
        ];
        for path in [
            r"\\nas\roms",
            r"\\nas\roms\Game",
            r"\\NAS\ROMS\Game\disc 1.cue",
            "//nas/roms/Game",
            r"\/nas\roms\Game",
            r"\\nas\\roms\\Game",
            r"\\other\archive\retro\x",
            r"  \\nas\roms\Game  ",
        ] {
            assert!(is_under_trusted_share(path, &roots), "refused: {path}");
        }
        for path in [
            // Another host, however alike.
            r"\\attacker\roms\Game",
            r"\\nas.evil.example\roms\Game",
            r"\\nas2\roms",
            r"\\nas.\roms",
            // Another share on the trusted host.
            r"\\nas\other",
            r"\\nas\romsx",
            r"\\nas",
            r"\\other\Archive",
            r"\\other\Archive\Other\x",
            // Traversal, device and verbatim forms never match.
            r"\\nas\roms\..\other",
            r"\\nas\roms\.\Game",
            r"\\?\UNC\nas\roms",
            r"\\?\nas\roms",
            r"\\.\nas\roms",
            r"\??\UNC\nas\roms",
            // Not UNC at all.
            r"C:\roms",
            "/mnt/roms",
            "",
        ] {
            assert!(!is_under_trusted_share(path, &roots), "trusted: {path}");
        }
    }

    #[test]
    fn nothing_is_trusted_without_a_list() {
        let none: [String; 0] = [];
        assert!(!is_under_trusted_share(r"\\nas\roms\Game", &none));
    }

    #[test]
    fn only_ascii_case_folding_so_a_lookalike_host_never_matches() {
        // U+212A KELVIN SIGN lowercases to ASCII `k` under Unicode folding.
        let roots = [r"\\nask\roms".to_string()];
        assert!(is_under_trusted_share(r"\\NASK\roms", &roots));
        assert!(!is_under_trusted_share("\\\\nas\u{212A}\\roms", &roots));
        assert!(!is_under_trusted_share(
            "\\\\nas\u{212A}\\roms\\Game",
            &roots
        ));
    }

    #[test]
    fn a_malformed_root_in_the_list_trusts_nothing() {
        let roots = [
            r"\\nas".to_string(),
            r"\\?\UNC\nas\roms".to_string(),
            "garbage".to_string(),
        ];
        assert!(!is_under_trusted_share(r"\\nas\roms", &roots));
        assert!(!is_under_trusted_share(r"\\nas\anything", &roots));
    }

    #[test]
    fn plain_unc_detection_for_os_reported_folders() {
        assert!(is_plain_unc(r"\\fs01\users$\chris\Documents"));
        assert!(!is_plain_unc(r"C:\Users\chris\Documents"));
        assert!(!is_plain_unc(r"\\?\UNC\fs01\users"));
        assert!(!is_plain_unc("/home/chris"));
    }

    #[test]
    fn stored_list_reads_back_and_a_hand_edited_file_can_only_trust_less() {
        let dir = tempfile::tempdir().unwrap();
        let file = dir.path().join("trusted_shares.json");
        assert!(read_share_roots(&file).is_empty());

        std::fs::write(&file, "not json").unwrap();
        assert!(read_share_roots(&file).is_empty());

        std::fs::write(
            &file,
            r#"{"roots":["\\\\nas\\roms","C:\\Windows","\\\\?\\UNC\\evil\\x","\\\\nas\\roms\\..\\x"]}"#,
        )
        .unwrap();
        assert_eq!(read_share_roots(&file), vec![r"\\nas\roms".to_string()]);

        std::fs::write(&file, "{}").unwrap();
        assert!(read_share_roots(&file).is_empty());
    }
}
