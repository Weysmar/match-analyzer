#![allow(dead_code)]

use std::path::{Path, PathBuf};
use std::process::{Command, Output};

pub fn replays_dir(group: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../../tests/fixtures/replays")
        .join(group)
}

/// The replays of a group, sorted. Empty when the group is not on this machine: only `public` is
/// in CI, the others hold personal replays.
pub fn replays(group: &str) -> Vec<PathBuf> {
    let Ok(entries) = std::fs::read_dir(replays_dir(group)) else {
        return Vec::new();
    };
    let mut files: Vec<PathBuf> = entries
        .flatten()
        .map(|entry| entry.path())
        .filter(|path| {
            path.extension()
                .is_some_and(|extension| extension == "replay")
        })
        .collect();
    files.sort();
    files
}

pub fn public_replays() -> Vec<PathBuf> {
    let files = replays("public");
    assert!(
        !files.is_empty(),
        "no public replay: run `just corpus-fetch`"
    );
    files
}

/// Public replays and the personal ones when present, without their " - Copie" duplicates.
pub fn all_replays() -> Vec<PathBuf> {
    let mut files = public_replays();
    files.extend(replays("vincent"));
    files.extend(replays("legacy"));
    files.retain(|path| !path.to_string_lossy().contains(" - Copie"));
    // 75 124 frames: subtr-actor's stats take minutes on this one. See its own test.
    files.retain(|path| !path.to_string_lossy().contains(SLOW_REPLAY));
    files
}

pub const SLOW_REPLAY: &str = "9AC15BE24A56EEF46EF4EEB56A2040A6";

pub fn rl_parse(args: &[&std::ffi::OsStr]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_rl-parse"))
        .args(args)
        .output()
        .expect("run rl-parse")
}

pub fn temp_dir(label: &str) -> PathBuf {
    let directory = std::env::temp_dir().join(format!("rl-parse-{label}-{}", std::process::id()));
    std::fs::create_dir_all(&directory).expect("temp dir");
    directory
}

pub struct Run {
    pub code: Option<i32>,
    pub stderr: String,
}

pub fn parse_header(input: &Path, output: &Path) -> Run {
    let run = rl_parse(&[
        "--header".as_ref(),
        "--input".as_ref(),
        input.as_os_str(),
        "--output".as_ref(),
        output.as_os_str(),
    ]);
    Run {
        code: run.status.code(),
        stderr: String::from_utf8_lossy(&run.stderr).into_owned(),
    }
}

pub fn parse_frames(input: &Path, output_dir: &Path) -> Run {
    let run = rl_parse(&[
        "--frames".as_ref(),
        "--input".as_ref(),
        input.as_os_str(),
        "--output-dir".as_ref(),
        output_dir.as_os_str(),
    ]);
    Run {
        code: run.status.code(),
        stderr: String::from_utf8_lossy(&run.stderr).into_owned(),
    }
}

pub fn error_code(run: &Run) -> String {
    let line: serde_json::Value = serde_json::from_str(run.stderr.trim()).expect("one JSON line");
    line["code"].as_str().expect("code").to_owned()
}
