//! Resolve a Mac application's declared entry point without traversing helpers.
use std::fs::{self, File};
use std::io::{Cursor, Read};
use std::path::{Path, PathBuf};

const MAX_INFO_BYTES: u64 = 1024 * 1024;
const MAX_INFO_DEPTH: usize = 64;
const MAX_INFO_EVENTS: usize = 16_384;

fn declared_executable(bytes: Vec<u8>) -> Option<String> {
    use plist::stream::{Event, Reader};

    let mut depth = 0_usize;
    let mut finished = false;
    let mut expect_key = true;
    let mut executable_key = false;
    let mut executable = None;
    let mut scalar_bytes = 0_u64;
    for (index, event) in Reader::new(Cursor::new(bytes)).enumerate() {
        if index >= MAX_INFO_EVENTS || finished {
            return None;
        }
        let event = event.ok()?;
        let size = match &event {
            Event::String(value) => value.len(),
            Event::Data(value) => value.len(),
            _ => 0,
        };
        scalar_bytes = scalar_bytes.checked_add(size as u64)?;
        // Binary references can expand to more data than their encoded size.
        if scalar_bytes > MAX_INFO_BYTES * 2 {
            return None;
        }
        if index == 0 {
            if !matches!(event, Event::StartDictionary(_)) {
                return None;
            }
            depth = 1;
            continue;
        }
        if matches!(event, Event::EndCollection) {
            if depth == 0 || (depth == 1 && !expect_key) {
                return None;
            }
            depth -= 1;
            finished = depth == 0;
            continue;
        }
        if depth == 1 {
            if expect_key {
                let Event::String(key) = &event else {
                    return None;
                };
                executable_key = key == "CFBundleExecutable";
                expect_key = false;
                continue;
            }
            if executable_key {
                let Event::String(name) = &event else {
                    return None;
                };
                if executable.is_some() {
                    return None;
                }
                executable = Some(name.to_string());
            }
            expect_key = true;
        }
        if matches!(event, Event::StartArray(_) | Event::StartDictionary(_)) {
            depth += 1;
            if depth > MAX_INFO_DEPTH {
                return None;
            }
        }
    }
    if finished {
        executable
    } else {
        None
    }
}

pub(crate) fn is_app_bundle(path: &Path) -> bool {
    path.extension()
        .is_some_and(|extension| extension.eq_ignore_ascii_case("app"))
        && path.is_dir()
}

pub(crate) fn executable_path(
    bundle: &Path,
    is_launchable: impl Fn(&Path) -> bool,
) -> Option<PathBuf> {
    if !is_app_bundle(bundle) {
        return None;
    }
    let root = bundle.canonicalize().ok()?;
    let info = root.join("Contents/Info.plist").canonicalize().ok()?;
    if !info.starts_with(&root) {
        return None;
    }
    if !fs::metadata(&info).ok()?.is_file() {
        return None;
    }
    let file = File::open(info).ok()?;
    let metadata = file.metadata().ok()?;
    if !metadata.is_file() || metadata.len() > MAX_INFO_BYTES {
        return None;
    }
    // Bound the read again so a growing file cannot bypass the metadata check.
    let mut bytes = Vec::new();
    file.take(MAX_INFO_BYTES + 1).read_to_end(&mut bytes).ok()?;
    if bytes.len() as u64 > MAX_INFO_BYTES {
        return None;
    }
    let name = declared_executable(bytes)?;
    // A backslash is a valid literal filename character on macOS.
    if name.is_empty() || matches!(name.as_str(), "." | "..") || name.contains(['/', '\0']) {
        return None;
    }
    let candidate = bundle.join("Contents/MacOS").join(name);
    let executable = candidate.canonicalize().ok()?;
    if !executable.starts_with(&root) || !executable.is_file() || !is_launchable(&executable) {
        return None;
    }
    // The caller relocates this path when a staging directory is promoted.
    // Validate canonical containment, but preserve its supplied staging prefix.
    Some(candidate)
}

#[cfg(test)]
mod tests {
    use super::*;
    use plist::{Dictionary, Value};
    use std::fs;
    use std::path::{Path, PathBuf};
    use tempfile::tempdir;

    fn bundle(root: &Path, name: &str, binary: bool) -> PathBuf {
        let app = root.join("Owned Game.app");
        fs::create_dir_all(app.join("Contents/MacOS")).unwrap();
        let mut info = Dictionary::new();
        info.insert("CFBundleExecutable".into(), Value::String(name.into()));
        let value = Value::Dictionary(info);
        let path = app.join("Contents/Info.plist");
        if binary {
            value.to_file_binary(path).unwrap();
        } else {
            value.to_file_xml(path).unwrap();
        }
        app
    }

    fn regular_file(path: &Path) -> bool {
        path.is_file()
    }

    #[test]
    fn declared_main_is_selected_over_helpers_for_xml_and_binary_metadata() {
        for binary in [false, true] {
            let work = tempdir().unwrap();
            let app = bundle(work.path(), "Main Game", binary);
            let main = app.join("Contents/MacOS/Main Game");
            fs::write(&main, b"owned fixture; never executed").unwrap();
            fs::write(app.join("Contents/MacOS/AAA-helper"), b"helper").unwrap();
            assert_eq!(executable_path(&app, regular_file), Some(main));
        }
    }

    #[test]
    fn lexical_staging_prefix_is_preserved_for_install_promotion() {
        let work = tempdir().unwrap();
        let app = bundle(work.path(), "Main", false);
        fs::write(app.join("Contents/MacOS/Main"), b"owned fixture").unwrap();
        let parent = work.path().join("parent");
        fs::create_dir(&parent).unwrap();
        let lexical_app = parent.join("..").join("Owned Game.app");
        assert_eq!(
            executable_path(&lexical_app, regular_file),
            Some(lexical_app.join("Contents/MacOS/Main"))
        );
    }

    #[test]
    fn non_application_directory_is_not_a_bundle_candidate() {
        let work = tempdir().unwrap();
        let app = bundle(work.path(), "Main", false);
        fs::write(app.join("Contents/MacOS/Main"), b"main").unwrap();
        let ordinary = work.path().join("ordinary");
        fs::rename(app, &ordinary).unwrap();
        assert!(!is_app_bundle(&ordinary));
        assert_eq!(executable_path(&ordinary, regular_file), None);
    }

    #[test]
    fn missing_or_non_launchable_main_never_falls_back_to_a_helper() {
        let work = tempdir().unwrap();
        let app = bundle(work.path(), "Main", false);
        fs::write(app.join("Contents/MacOS/helper"), b"helper").unwrap();
        assert_eq!(executable_path(&app, regular_file), None);
        fs::write(app.join("Contents/MacOS/Main"), b"main").unwrap();
        assert_eq!(executable_path(&app, |_| false), None);
    }

    #[test]
    fn missing_malformed_non_dictionary_and_non_string_info_are_rejected() {
        let work = tempdir().unwrap();
        let app = bundle(work.path(), "Main", false);
        let info = app.join("Contents/Info.plist");
        fs::remove_file(&info).unwrap();
        assert_eq!(executable_path(&app, regular_file), None);
        for bytes in [
            b"not a property list".as_slice(),
            b"<plist><dict>".as_slice(),
        ] {
            fs::write(&info, bytes).unwrap();
            assert_eq!(executable_path(&app, regular_file), None);
        }
        for value in [Value::Array(vec![]), Value::Dictionary(Dictionary::new())] {
            value.to_file_xml(&info).unwrap();
            assert_eq!(executable_path(&app, regular_file), None);
        }
        let mut d = Dictionary::new();
        d.insert("CFBundleExecutable".into(), Value::Boolean(true));
        Value::Dictionary(d).to_file_binary(&info).unwrap();
        assert_eq!(executable_path(&app, regular_file), None);
    }

    #[test]
    fn unsafe_declarations_are_rejected() {
        for name in ["", ".", "..", "../outside", "/outside", "nested/main"] {
            let work = tempdir().unwrap();
            let app = bundle(work.path(), name, false);
            assert_eq!(executable_path(&app, regular_file), None, "{name:?}");
        }
    }

    #[test]
    fn oversized_metadata_is_rejected_before_parsing() {
        let work = tempdir().unwrap();
        let app = bundle(work.path(), "Main", false);
        fs::write(app.join("Contents/Info.plist"), vec![b' '; 1024 * 1024 + 1]).unwrap();
        assert_eq!(executable_path(&app, regular_file), None);
    }

    #[test]
    fn excessive_metadata_nesting_is_rejected_without_building_a_value_tree() {
        let work = tempdir().unwrap();
        let app = bundle(work.path(), "Main", false);
        fs::write(app.join("Contents/MacOS/Main"), b"owned fixture").unwrap();
        let xml = format!(
            "<plist version=\"1.0\"><dict><key>CFBundleExecutable</key><string>Main</string><key>Opaque</key>{}<string>leaf</string>{}</dict></plist>",
            "<array>".repeat(128), "</array>".repeat(128)
        );
        fs::write(app.join("Contents/Info.plist"), xml).unwrap();
        assert_eq!(executable_path(&app, regular_file), None);
    }

    #[test]
    fn excessive_metadata_events_are_rejected() {
        let work = tempdir().unwrap();
        let app = bundle(work.path(), "Main", false);
        fs::write(app.join("Contents/MacOS/Main"), b"owned fixture").unwrap();
        let mut xml = String::from(
            "<plist version=\"1.0\"><dict><key>CFBundleExecutable</key><string>Main</string>",
        );
        for index in 0..9000 {
            xml.push_str(&format!("<key>k{index}</key><true/>"));
        }
        xml.push_str("</dict></plist>");
        fs::write(app.join("Contents/Info.plist"), xml).unwrap();
        assert_eq!(executable_path(&app, regular_file), None);
    }

    #[test]
    fn ordinary_nested_metadata_does_not_override_the_top_level_main() {
        for binary in [false, true] {
            let work = tempdir().unwrap();
            let app = bundle(work.path(), "Main", binary);
            let main = app.join("Contents/MacOS/Main");
            fs::write(&main, b"owned fixture").unwrap();
            let mut nested = Dictionary::new();
            nested.insert(
                "CFBundleExecutable".into(),
                Value::String("not-main".into()),
            );
            let mut info = Dictionary::new();
            info.insert(
                "Opaque".into(),
                Value::Array(vec![Value::Dictionary(nested)]),
            );
            info.insert("CFBundleExecutable".into(), Value::String("Main".into()));
            info.insert("Version".into(), Value::String("1".into()));
            let value = Value::Dictionary(info);
            if binary {
                value
                    .to_file_binary(app.join("Contents/Info.plist"))
                    .unwrap();
            } else {
                value.to_file_xml(app.join("Contents/Info.plist")).unwrap();
            }
            assert_eq!(executable_path(&app, regular_file), Some(main));
        }
    }

    #[test]
    fn duplicate_main_keys_odd_dictionaries_and_extra_roots_are_rejected() {
        let work = tempdir().unwrap();
        let app = bundle(work.path(), "Main", false);
        fs::write(app.join("Contents/MacOS/Main"), b"owned fixture").unwrap();
        for body in [
            "<dict><key>CFBundleExecutable</key><string>Main</string><key>CFBundleExecutable</key><string>Main</string></dict>",
            "<dict><key>CFBundleExecutable</key><string>Main</string><key>missing</key></dict>",
            "<dict><key>CFBundleExecutable</key><string>Main</string></dict><dict/>",
        ] {
            fs::write(app.join("Contents/Info.plist"), format!("<plist version=\"1.0\">{body}</plist>")).unwrap();
            assert_eq!(executable_path(&app, regular_file), None);
        }
    }

    #[test]
    fn repeated_binary_scalar_references_cannot_bypass_the_expanded_budget() {
        let work = tempdir().unwrap();
        let app = bundle(work.path(), "Main", true);
        fs::write(app.join("Contents/MacOS/Main"), b"owned fixture").unwrap();
        let mut info = Dictionary::new();
        info.insert("CFBundleExecutable".into(), Value::String("Main".into()));
        info.insert(
            "Opaque".into(),
            Value::Array(vec![Value::String("x".repeat(200_000)); 12]),
        );
        let path = app.join("Contents/Info.plist");
        Value::Dictionary(info).to_file_binary(&path).unwrap();
        assert!(fs::metadata(&path).unwrap().len() < MAX_INFO_BYTES);
        assert_eq!(executable_path(&app, regular_file), None);
    }

    #[cfg(unix)]
    #[test]
    fn metadata_and_executable_symlink_escapes_are_rejected() {
        use std::os::unix::fs::symlink;
        let work = tempdir().unwrap();
        let app = bundle(work.path(), "Main", false);
        let outside = work.path().join("outside");
        fs::write(&outside, b"outside").unwrap();
        symlink(&outside, app.join("Contents/MacOS/Main")).unwrap();
        assert_eq!(executable_path(&app, regular_file), None);
        let info = app.join("Contents/Info.plist");
        let external_info = work.path().join("external.plist");
        fs::rename(&info, &external_info).unwrap();
        symlink(external_info, info).unwrap();
        assert_eq!(executable_path(&app, regular_file), None);
    }

    #[cfg(unix)]
    #[test]
    fn a_literal_backslash_in_a_mac_filename_is_not_a_path_separator() {
        let work = tempdir().unwrap();
        let app = bundle(work.path(), "Main\\Game", false);
        let main = app.join("Contents/MacOS/Main\\Game");
        fs::write(&main, b"owned fixture; never executed").unwrap();
        assert_eq!(executable_path(&app, regular_file), Some(main));
    }
}
