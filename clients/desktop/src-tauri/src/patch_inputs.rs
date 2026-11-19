//! Resolve transport containers before invoking Flips. Each apply owns its work directory.
use std::fs::File;
use std::io::{self, Read};
use std::path::{Path, PathBuf};
use zip::ZipArchive;

#[derive(Clone, Copy)]
pub enum Input {
    Rom,
    Patch,
}

fn prefix(path: &Path) -> Result<Vec<u8>, String> {
    let mut bytes = Vec::with_capacity(5);
    File::open(path)
        .and_then(|f| f.take(5).read_to_end(&mut bytes))
        .map_err(|e| e.to_string())?;
    Ok(bytes)
}

fn candidate(path: &Path, kind: Input) -> bool {
    let ext = path
        .extension()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    match kind {
        Input::Patch => matches!(ext.as_str(), "ips" | "bps" | "ups"),
        Input::Rom => matches!(
            ext.as_str(),
            "rom"
                | "nes"
                | "fds"
                | "sfc"
                | "smc"
                | "gb"
                | "gbc"
                | "gba"
                | "nds"
                | "n64"
                | "z64"
                | "v64"
                | "sms"
                | "gg"
                | "sg"
                | "gen"
                | "md"
                | "smd"
                | "bin"
                | "a26"
                | "a52"
                | "a78"
                | "lnx"
                | "pce"
                | "ws"
                | "wsc"
                | "ngp"
                | "ngc"
        ),
    }
}

pub fn prepare(source: &Path, work: &Path, kind: Input) -> Result<PathBuf, String> {
    let name = match kind {
        Input::Rom => "ROM",
        Input::Patch => "patch",
    };
    let header = prefix(source)?;
    let path = if header.starts_with(b"PK\x03\x04") || header.starts_with(b"PK\x05\x06") {
        let file = File::open(source).map_err(|e| e.to_string())?;
        let mut zip = ZipArchive::new(file).map_err(|e| e.to_string())?;
        let mut chosen = None;
        for index in 0..zip.len() {
            let entry = zip.by_index(index).map_err(|e| e.to_string())?;
            let Some(rel) = entry.enclosed_name() else {
                continue;
            };
            if entry.is_dir()
                || rel.components().any(|c| {
                    c.as_os_str().to_string_lossy().starts_with('.') || c.as_os_str() == "__MACOSX"
                })
                || !candidate(&rel, kind)
            {
                continue;
            }
            if chosen.is_some() {
                return Err(format!(
                    "Multiple {name} files in archive. Choose the correct input in Flips manually."
                ));
            }
            let basename = rel
                .file_name()
                .ok_or("Invalid archive member name")?
                .to_string_lossy();
            chosen = Some((index, super::sanitize_mod_filename(&basename)));
        }
        let (index, filename) = chosen.ok_or_else(|| {
            format!("No supported {name} file in archive. Select the input in Flips manually.")
        })?;
        let entry = zip.by_index(index).map_err(|e| e.to_string())?;
        let limit = match kind {
            Input::Rom => 1024 * 1024 * 1024,
            Input::Patch => 256 * 1024 * 1024,
        };
        if entry.size() > limit {
            return Err(format!("{name} exceeds extraction size limit"));
        }
        let dir = work.join(name);
        std::fs::create_dir(&dir).map_err(|e| e.to_string())?;
        let output = dir.join(filename);
        let mut file = File::create(&output).map_err(|e| e.to_string())?;
        let n = io::copy(&mut entry.take(limit + 1), &mut file).map_err(|e| e.to_string())?;
        if n > limit {
            return Err(format!("{name} exceeds extraction size limit"));
        }
        output
    } else {
        if matches!(kind, Input::Rom)
            && source
                .extension()
                .is_some_and(|ext| ext.eq_ignore_ascii_case("zip"))
        {
            return Err("This older download does not contain a ZIP. Download the base game again to recover its ROM name.".into());
        }
        source.to_path_buf()
    };
    if matches!(kind, Input::Patch) {
        let magic = prefix(&path)?;
        if ![&b"PATCH"[..], &b"BPS1"[..], &b"UPS1"[..]]
            .iter()
            .any(|sig| magic.starts_with(sig))
        {
            return Err("Unsupported patch bytes. Select an IPS, BPS or UPS patch.".into());
        }
    }
    Ok(path)
}

pub fn invoke_flips(
    flips: &Path,
    patch: &Path,
    rom: &Path,
    work: &Path,
    out: &Path,
) -> Result<(), String> {
    let generated = work.join("patched-output");
    let status = std::process::Command::new(flips)
        .arg("--apply")
        .arg(patch)
        .arg(rom)
        .arg(&generated)
        .status()
        .map_err(|error| format!("Failed to start Flips: {error}"))?;
    if !status.success() {
        return Err(format!("Flips exited with status {status}"));
    }
    // Publish the completed result without overwriting a previous patch or either input.
    std::fs::hard_link(&generated, out)
        .map_err(|e| format!("Could not publish patched ROM: {e}"))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use zip::write::{SimpleFileOptions, ZipWriter};

    fn archive(path: &Path, members: &[(&str, &[u8])]) {
        let mut writer = ZipWriter::new(File::create(path).unwrap());
        for (name, bytes) in members {
            writer
                .start_file(*name, SimpleFileOptions::default())
                .unwrap();
            writer.write_all(bytes).unwrap();
        }
        writer.finish().unwrap();
    }

    #[test]
    fn reads_payloads_and_keeps_rom_extension() {
        let temp = tempfile::tempdir().unwrap();
        let src = temp.path().join("download.zip");
        archive(
            &src,
            &[("folder/Example.sfc", b"base"), ("readme.txt", b"text")],
        );
        let extracted = prepare(&src, temp.path(), Input::Rom).unwrap();
        assert_eq!(extracted.extension().unwrap(), "sfc");
        assert_eq!(std::fs::read(extracted).unwrap(), b"base");
        let patch = temp.path().join("extra");
        archive(
            &patch,
            &[
                ("enable.ips", b"PATCHdata"),
                ("__MACOSX/enable.ips", b"metadata"),
            ],
        );
        assert_eq!(
            std::fs::read(prepare(&patch, temp.path(), Input::Patch).unwrap()).unwrap(),
            b"PATCHdata"
        );
    }

    #[test]
    fn rejects_ambiguous_or_mislabeled_content() {
        let temp = tempfile::tempdir().unwrap();
        let src = temp.path().join("base");
        archive(&src, &[("v1.sfc", b"a"), ("v2.sfc", b"b")]);
        assert!(prepare(&src, temp.path(), Input::Rom)
            .unwrap_err()
            .contains("Multiple"));
        let patch = temp.path().join("invalid.bps");
        std::fs::write(&patch, b"text").unwrap();
        assert!(prepare(&patch, temp.path(), Input::Patch).is_err());
    }

    #[test]
    #[ignore = "requires an installed Flips CLI in FLIPS_PATH"]
    fn actual_flips_applies_authored_ips_from_two_archives() {
        let flips =
            std::env::var_os("FLIPS_PATH").expect("Supply FLIPS_PATH to the real Flips executable");
        let temp = tempfile::tempdir().unwrap();
        let rom_zip = temp.path().join("base.zip");
        let patch_zip = temp.path().join("translation.zip");
        let source: Vec<u8> = (0..64).collect();
        archive(&rom_zip, &[("fixture.sfc", &source)]);
        archive(
            &patch_zip,
            &[("translation.ips", b"PATCH\0\0\x02\0\x03ODXEOF")],
        );
        let rom = prepare(&rom_zip, temp.path(), Input::Rom).unwrap();
        let patch = prepare(&patch_zip, temp.path(), Input::Patch).unwrap();
        let out = temp.path().join("translated.sfc");
        invoke_flips(Path::new(&flips), &patch, &rom, temp.path(), &out).unwrap();
        assert_eq!(std::fs::read(&rom).unwrap(), source);
        let mut expected = source;
        expected[2..5].copy_from_slice(b"ODX");
        assert_eq!(std::fs::read(&out).unwrap(), expected);
    }
}
