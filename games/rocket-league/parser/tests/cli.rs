//! Exit codes of the binary on bad input. No replay needed: these run everywhere.

mod common;

use common::{Run, error_code, parse_frames, parse_header, rl_parse, temp_dir};

fn run_with_content(label: &str, content: &[u8]) -> (Run, Run) {
    let directory = temp_dir(label);
    let input = directory.join("input.replay");
    std::fs::write(&input, content).unwrap();
    let header = parse_header(&input, &directory.join("header.json"));
    let frames = parse_frames(&input, &directory.join("frames"));
    let produced =
        directory.join("header.json").exists() || directory.join("frames/frames.parquet").exists();
    std::fs::remove_dir_all(&directory).unwrap();
    assert!(!produced, "a refused file must leave no output");
    (header, frames)
}

fn assert_refused(label: &str, content: &[u8], code: &str, exit: i32) {
    let (header, frames) = run_with_content(label, content);
    assert_eq!(header.code, Some(exit), "{label} --header");
    assert_eq!(frames.code, Some(exit), "{label} --frames");
    assert_eq!(error_code(&header), code);
    assert_eq!(error_code(&frames), code);
}

fn exit_of(args: &[&str]) -> Option<i32> {
    let args: Vec<&std::ffi::OsStr> = args.iter().map(std::ffi::OsStr::new).collect();
    let output = rl_parse(&args);
    if !output.status.success() {
        let line: serde_json::Value =
            serde_json::from_slice(&output.stderr).expect("one JSON line on stderr");
        assert_eq!(line["code"], "usage");
    }
    output.status.code()
}

#[test]
fn bad_command_lines_are_usage_errors() {
    for args in [
        &[][..],
        &["--header"],
        &["--header", "--input", "x"],
        &["--frames", "--input", "x"],
        &[
            "--header",
            "--frames",
            "--input",
            "x",
            "--output",
            "y",
            "--output-dir",
            "z",
        ],
        &["--header", "--input", "x", "--output", "y", "--fps", "30"],
        &[
            "--frames",
            "--input",
            "x",
            "--output-dir",
            "z",
            "--fps",
            "0",
        ],
        &[
            "--frames",
            "--input",
            "x",
            "--output-dir",
            "z",
            "--fps",
            "nope",
        ],
        &["--unknown"],
    ] {
        assert_eq!(exit_of(args), Some(2), "{args:?}");
    }
}

#[test]
fn help_and_version_succeed() {
    assert_eq!(rl_parse(&["--help".as_ref()]).status.code(), Some(0));
    assert_eq!(rl_parse(&["--version".as_ref()]).status.code(), Some(0));
}

#[test]
fn a_missing_file_is_not_a_replay() {
    let missing = temp_dir("missing").join("nothing.replay");
    let run = parse_header(&missing, &missing.with_extension("json"));
    assert_eq!(run.code, Some(10));
    assert_eq!(error_code(&run), "not_a_replay");
}

#[test]
fn an_empty_file_is_not_a_replay() {
    assert_refused("empty", b"", "not_a_replay", 10);
}

#[test]
fn another_kind_of_file_is_not_a_replay() {
    assert_refused(
        "png",
        b"\x89PNG\r\n\x1a\nnot a replay at all",
        "not_a_replay",
        10,
    );
}

#[test]
fn twenty_megabytes_of_noise_are_not_a_replay() {
    // A simple generator is enough: this only has to look like nothing.
    let mut state = 0x2545_F491_4F6C_DD1Du64;
    let noise: Vec<u8> = (0..20 * 1024 * 1024)
        .map(|_| {
            state ^= state << 13;
            state ^= state >> 7;
            state ^= state << 17;
            state as u8
        })
        .collect();
    assert_refused("noise", &noise, "not_a_replay", 10);
}

#[test]
fn a_replay_prefix_alone_is_corrupt() {
    assert_refused(
        "prefix",
        b"\x10\0\0\0\0\0\0\0TAGame.Replay_Soccar_TA",
        "corrupt",
        11,
    );
}
