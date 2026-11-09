//! Checks on real replays: `just test-replays`. Ignored by a plain `cargo test`, since they need
//! the corpus and run in release mode. Failures name files, never players.

mod common;

use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};
use std::time::Instant;

use arrow::array::{Array, BooleanArray, Float32Array, UInt8Array};
use boxcars::{HeaderProp, ParserBuilder};
use common::{
    SLOW_REPLAY, all_replays, error_code, parse_frames, parse_header, public_replays, replays,
    temp_dir,
};
use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;
use rl_parse::error::Failure;
use rl_parse::{events, frames, header, identity, output};
use serde_json::{Value, json};
use subtr_actor::{StatsCollector, StatsFrameResolution, StatsTimelineEventCollector};

fn name(path: &Path) -> String {
    path.file_name().unwrap().to_string_lossy().into_owned()
}

fn read(path: &Path) -> Vec<u8> {
    std::fs::read(path).unwrap()
}

fn is_dropshot(path: &Path) -> bool {
    let replay = header::parse(&read(path)).unwrap();
    replay.properties.iter().any(|(key, value)| {
        key == "MapName" && matches!(value, HeaderProp::Name(map) | HeaderProp::Str(map) if map == "ShatterShot_P")
    })
}

/// What the parser analyzes. The rest must fail with `unsupported_mode`, by design.
fn collected(path: &Path) -> Option<(boxcars::Replay, frames::Collected)> {
    let replay = frames::parse(&read(path)).unwrap_or_else(|f| panic!("{}: {f:?}", name(path)));
    match frames::collect(&replay, None) {
        Ok(collected) => Some((replay, collected)),
        Err(Failure::UnsupportedMode) => None,
        Err(failure) => panic!("{}: {failure:?}", name(path)),
    }
}

// ---------------------------------------------------------------------------------- snapshots

/// Replaces what identifies a player or a match, keeping the structure: the snapshots are
/// versioned, the replays are not.
fn anonymize(mut value: Value) -> Value {
    let mut names: HashMap<String, usize> = HashMap::new();
    let alias = |name: &str, names: &mut HashMap<String, usize>| {
        let next = names.len();
        format!("player{}", names.entry(name.to_owned()).or_insert(next))
    };
    for key in ["match_guid", "replay_id"] {
        if value[key].is_string() {
            value[key] = json!("<id>");
        }
    }
    for player in value["players"].as_array_mut().unwrap() {
        player["name"] = json!(alias(player["name"].as_str().unwrap(), &mut names));
        if player["platform_id"].is_string() {
            player["platform_id"] = json!("<id>");
        }
    }
    for goal in value["goals"].as_array_mut().unwrap() {
        if let Some(player) = goal["player_name"].as_str().map(str::to_owned) {
            goal["player_name"] = json!(alias(&player, &mut names));
        }
    }
    value["parser_version"] = json!("<version>");
    value
}

#[test]
#[ignore = "needs the replay corpus: just test-replays"]
fn headers_match_their_snapshots() {
    let directory = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/snapshots");
    std::fs::create_dir_all(&directory).unwrap();
    let update = std::env::var_os("UPDATE_SNAPSHOTS").is_some();
    let mut failures = Vec::new();
    for path in public_replays() {
        let replay = header::parse(&read(&path)).unwrap();
        let value = anonymize(serde_json::to_value(header::extract(&replay)).unwrap());
        let text = format!("{}\n", serde_json::to_string_pretty(&value).unwrap());
        let snapshot = directory.join(name(&path)).with_extension("json");
        if update {
            std::fs::write(&snapshot, text).unwrap();
        } else if std::fs::read_to_string(&snapshot).ok().as_deref() != Some(text.as_str()) {
            failures.push(name(&path));
        }
    }
    assert!(
        failures.is_empty(),
        "differs from its snapshot: {failures:?}"
    );
}

// ------------------------------------------------------------------------------------- binary

#[test]
#[ignore = "needs the replay corpus: just test-replays"]
fn the_binary_writes_its_outputs() {
    let directory = temp_dir("outputs");
    for path in public_replays() {
        let label = name(&path);
        let out = directory.join(&label);
        let header_path = out.with_extension("json");
        assert_eq!(
            parse_header(&path, &header_path).code,
            Some(0),
            "{label} --header"
        );
        let value: Value = serde_json::from_slice(&read(&header_path)).unwrap();
        assert_eq!(value["schema_version"], 1, "{label}");

        let run = parse_frames(&path, &out);
        if is_dropshot(&path) {
            assert_eq!(run.code, Some(14), "{label}");
            assert_eq!(error_code(&run), "unsupported_mode");
            continue;
        }
        if run.code == Some(14) {
            continue; // other non-standard playlists: checked below.
        }
        assert_eq!(run.code, Some(0), "{label} --frames");
        assert!(
            run.stderr.is_empty(),
            "{label}: stderr must be silent on success"
        );
        let events: Value = serde_json::from_slice(&read(&out.join("events.json"))).unwrap();
        assert_eq!(events["schema_version"], 2, "{label}");
        // subtr-actor's detectors ran on every replay of the standard mode (T11.1).
        for key in ["touches", "kickoffs", "fifty_fifties", "beaten_to_ball"] {
            assert!(events[key].is_array(), "{label}: {key}");
        }
        assert!(
            !events["touches"].as_array().unwrap().is_empty(),
            "{label}: no touch"
        );
        let file = std::fs::File::open(out.join("frames.parquet")).unwrap();
        let reader = ParquetRecordBatchReaderBuilder::try_new(file).unwrap();
        assert_eq!(
            *reader.schema().as_ref(),
            output::frames_schema(),
            "{label}"
        );
    }
    std::fs::remove_dir_all(&directory).unwrap();
}

#[test]
#[ignore = "needs the replay corpus: just test-replays"]
fn only_non_standard_modes_are_refused() {
    let mut refused = Vec::new();
    for path in public_replays() {
        if collected(&path).is_none() {
            refused.push(name(&path));
        }
    }
    assert!(
        refused.iter().any(|file| file.contains("dropshot")),
        "{refused:?}"
    );
    assert!(refused.len() <= 3, "unexpected refusals: {refused:?}");
}

// --------------------------------------------------------------------------------- invariants

fn floats<'a>(batch: &'a arrow::array::RecordBatch, column: &str) -> &'a Float32Array {
    batch
        .column_by_name(column)
        .unwrap()
        .as_any()
        .downcast_ref()
        .unwrap()
}

fn flags<'a>(batch: &'a arrow::array::RecordBatch, column: &str) -> &'a BooleanArray {
    batch
        .column_by_name(column)
        .unwrap()
        .as_any()
        .downcast_ref()
        .unwrap()
}

#[test]
#[ignore = "needs the replay corpus: just test-replays"]
fn frames_hold_their_invariants() {
    for path in all_replays() {
        let label = name(&path);
        let Some((replay, collected)) = collected(&path) else {
            continue;
        };
        let batch = output::frames_batch(&collected).unwrap();
        let (x, y, z) = (
            floats(&batch, "x"),
            floats(&batch, "y"),
            floats(&batch, "z"),
        );
        let boost = floats(&batch, "boost");
        let (dt, time) = (floats(&batch, "dt_s"), floats(&batch, "time_s"));
        let (present, demolished) = (flags(&batch, "present"), flags(&batch, "demolished"));
        let phase: &UInt8Array = batch
            .column_by_name("phase")
            .unwrap()
            .as_any()
            .downcast_ref()
            .unwrap();
        let (qx, qy, qz, qw) = (
            floats(&batch, "qx"),
            floats(&batch, "qy"),
            floats(&batch, "qz"),
            floats(&batch, "qw"),
        );
        let modern = replay.net_version.unwrap_or(0) >= 7;
        for row in 0..batch.num_rows() {
            assert!(dt.value(row) >= 0.0, "{label}: negative dt");
            assert!(time.value(row).is_finite(), "{label}: time");
            assert_eq!(present.value(row), !x.is_null(row), "{label}: present");
            if x.is_null(row) {
                assert!(boost.is_null(row), "{label}: boost without a car");
                continue;
            }
            let value = boost.value(row);
            assert!((0.0..=100.0).contains(&value), "{label}: boost {value}");
            if modern {
                let norm = (qx.value(row).powi(2)
                    + qy.value(row).powi(2)
                    + qz.value(row).powi(2)
                    + qw.value(row).powi(2))
                .sqrt();
                assert!((norm - 1.0).abs() < 0.01, "{label}: quaternion {norm}");
            }
            if phase.value(row) == 3 && !demolished.value(row) {
                assert!(x.value(row).abs() <= 4200.0, "{label}: x {}", x.value(row));
                assert!(y.value(row).abs() <= 6100.0, "{label}: y {}", y.value(row));
                assert!(z.value(row) <= 2100.0, "{label}: z {}", z.value(row));
            }
        }
        assert!(!collected.arena_out_of_bounds(), "{label}: out of bounds");
    }
}

#[test]
#[ignore = "needs the replay corpus: just test-replays"]
fn the_fps_cap_keeps_the_game_time() {
    let path = &public_replays()
        .into_iter()
        .find(|p| name(p).starts_with("post-eac-ranked-doubles"))
        .unwrap();
    let replay = frames::parse(&read(path)).unwrap();
    let all = frames::collect(&replay, None).unwrap();
    let capped = frames::collect(&replay, Some(10.0)).unwrap();
    assert!(capped.kept.len() < all.kept.len() / 2);
    let total = |collected: &frames::Collected| -> f64 {
        let batch = output::frames_batch(collected).unwrap();
        let dt = floats(&batch, "dt_s");
        let players = collected.data.frame_data.players.len();
        (0..batch.num_rows())
            .step_by(players)
            .map(|row| f64::from(dt.value(row)))
            .sum()
    };
    assert!(
        (total(&all) - total(&capped)).abs() < 0.2,
        "{} {}",
        total(&all),
        total(&capped)
    );
}

// ------------------------------------------------------------------------- against subtr-actor

#[test]
#[ignore = "needs the replay corpus: just test-replays"]
fn phases_and_times_match_the_timeline() {
    for path in public_replays().into_iter().chain(replays("vincent")) {
        let label = name(&path);
        let Some((replay, collected)) = collected(&path) else {
            continue;
        };
        let timeline = StatsTimelineEventCollector::new()
            .with_frame_resolution(StatsFrameResolution::EveryFrame)
            .get_replay_stats_timeline_scaffold(&replay)
            .unwrap();
        let reference: HashMap<u32, _> = timeline
            .frames
            .iter()
            .map(|f| (f.time.to_bits(), (f.gameplay_phase, f.dt)))
            .collect();
        let times = collected.times();
        let mut previous = None;
        for (index, time) in times.iter().enumerate() {
            let (phase, dt) = reference[&time.to_bits()];
            assert_eq!(collected.phases[index], phase, "{label}: frame {index}");
            let ours = previous.map_or(0.0, |p: f32| time - p);
            assert!(
                (ours - dt).abs() < 1e-3,
                "{label}: frame {index}, dt {ours} against {dt}"
            );
            previous = Some(*time);
        }
    }
}

fn stats_of<'a>(modules: &'a Value, module: &str, id: &Value) -> &'a Value {
    modules[module]["player_stats"]
        .as_array()
        .and_then(|rows| rows.iter().find(|row| &row["player_id"] == id))
        .map_or(&Value::Null, |row| &row["stats"])
}

fn percentile(values: &mut [f64], q: f64) -> f64 {
    values.sort_by(f64::total_cmp);
    values[((values.len() - 1) as f64 * q) as usize]
}

#[test]
#[ignore = "needs the replay corpus: just test-replays"]
fn demolitions_and_pads_match_the_stats() {
    let (mut big, mut small) = (Vec::new(), Vec::new());
    let (mut unresolved, mut resolved) = (0u32, 0usize);
    let mut demolitions = 0;
    let mut files: Vec<PathBuf> = public_replays();
    files.extend(replays("vincent"));
    for path in files {
        let label = name(&path);
        let Some((replay, collected)) = collected(&path) else {
            continue;
        };
        if replay.net_version.unwrap_or(0) < 10 {
            continue;
        }
        let stats =
            serde_json::to_value(StatsCollector::new().get_stats(&replay).unwrap()).unwrap();
        let events = events::extract(&replay, &collected, None);
        unresolved += events.unresolved_pad_pickups;
        resolved += events.pad_pickups.len();
        demolitions += events.demolitions.len();
        for (index, (id, _)) in collected.data.frame_data.players.iter().enumerate() {
            let id = serde_json::to_value(id).unwrap();
            let demo = stats_of(&stats["modules"], "demo", &id);
            let count = |value: &Value, key: &str| value[key].as_f64().unwrap_or(0.0);
            let inflicted = events
                .demolitions
                .iter()
                .filter(|d| d.attacker_idx == Some(index))
                .count();
            let taken = events
                .demolitions
                .iter()
                .filter(|d| d.victim_idx == Some(index))
                .count();
            assert_eq!(inflicted as f64, count(demo, "demos_inflicted"), "{label}");
            assert_eq!(taken as f64, count(demo, "demos_taken"), "{label}");

            let boost = stats_of(&stats["modules"], "boost", &id);
            let pads = |size: &str| {
                events
                    .pad_pickups
                    .iter()
                    .filter(|p| p.player_idx == index && p.size == size && matches!(p.phase, 2 | 3))
                    .count() as f64
            };
            big.push((pads("big") - count(boost, "big_pads_collected")).abs());
            small.push((pads("small") - count(boost, "small_pads_collected")).abs());
        }
    }
    assert!(demolitions > 0);
    let report = format!("big {big:?}\nsmall {small:?}");
    println!(
        "pads: big median {} p95 {} max {}, small median {} p95 {} max {}, n {}",
        percentile(&mut big, 0.5),
        percentile(&mut big, 0.95),
        percentile(&mut big, 1.0),
        percentile(&mut small, 0.5),
        percentile(&mut small, 0.95),
        percentile(&mut small, 1.0),
        big.len()
    );
    assert_eq!(percentile(&mut big, 0.5), 0.0, "{report}");
    assert_eq!(percentile(&mut small, 0.5), 0.0, "{report}");
    // Measured: 3 with Vincent's recent replays, 4 on the public ones alone, which is what CI has.
    // The rest comes from pickups subtr-actor infers from boost increases.
    assert!(
        percentile(&mut big, 0.95) <= 4.0,
        "big p95 {}",
        percentile(&mut big, 0.95)
    );
    assert!(
        percentile(&mut small, 0.95) <= 5.0,
        "small p95 {}",
        percentile(&mut small, 0.95)
    );
    assert!(
        f64::from(unresolved) < 0.005 * resolved as f64,
        "{unresolved} of {resolved}"
    );
}

#[test]
#[ignore = "needs the replay corpus: just test-replays"]
fn a_demolished_car_is_marked_until_its_respawn() {
    for path in public_replays() {
        let Some((_, collected)) = collected(&path) else {
            continue;
        };
        let times = collected.times();
        for demolition in &collected.data.demolish_infos {
            let player = collected
                .data
                .frame_data
                .players
                .iter()
                .position(|(id, _)| *id == demolition.victim)
                .unwrap();
            let at = times.partition_point(|t| *t < demolition.time);
            if at < times.len() {
                assert!(collected.demolished[player][at], "{}", name(&path));
            }
            // A second demolition can follow the respawn: it has its own window.
            let next = collected
                .data
                .demolish_infos
                .iter()
                .filter(|other| other.victim == demolition.victim && other.time > demolition.time)
                .map(|other| other.time)
                .fold(f32::INFINITY, f32::min);
            let last = collected.demolished[player]
                .iter()
                .zip(&times)
                .filter(|(flag, time)| **flag && **time >= demolition.time && **time < next)
                .map(|(_, time)| *time)
                .fold(demolition.time, f32::max);
            assert!(
                last - demolition.time <= frames::DEMOLISHED_SECONDS,
                "{}",
                name(&path)
            );
        }
    }
}

// ----------------------------------------------------------------------------------- identity

#[test]
#[ignore = "needs the replay corpus: just test-replays"]
fn header_and_network_ids_agree() {
    let mut compared: BTreeMap<&str, u32> = BTreeMap::new();
    let mut absent = 0;
    for path in public_replays().into_iter().chain(replays("vincent")) {
        let Some((replay, collected)) = collected(&path) else {
            continue;
        };
        if replay.net_version.unwrap_or(0) < 11 {
            continue;
        }
        let head = header::extract(&replay);
        let network: Vec<(&str, Option<String>)> = collected
            .data
            .frame_data
            .players
            .iter()
            .map(|(id, _)| identity::from_remote_id(id))
            .collect();
        for player in &head.players {
            let Some(id) = &player.platform_id else {
                continue;
            };
            let found = network
                .iter()
                .any(|(kind, value)| *kind == player.platform && value.as_ref() == Some(id));
            if found {
                *compared.entry(player.platform).or_default() += 1;
            } else {
                absent += 1;
            }
        }
    }
    assert!(
        compared.get("epic").copied().unwrap_or(0) > 10,
        "{compared:?}"
    );
    assert!(
        compared.get("steam").copied().unwrap_or(0) > 0,
        "{compared:?}"
    );
    // Spectators are filtered out: every player of the header is on the network.
    assert_eq!(absent, 0, "{compared:?}");
}

#[test]
#[ignore = "needs the replay corpus: just test-replays"]
fn anonymized_players_keep_their_wish() {
    let mut anonymized = 0;
    for path in replays("vincent") {
        let Some((replay, collected)) = collected(&path) else {
            continue;
        };
        let events = events::extract(&replay, &collected, None);
        let head = header::extract(&replay);
        for player in events.roster.iter().filter(|player| player.anonymized) {
            anonymized += 1;
            assert!(!player.name.is_empty(), "{}", name(&path));
            assert!(
                !head.players.iter().any(|p| p.name == player.name),
                "{}: the real name is exposed",
                name(&path)
            );
        }
    }
    if !replays("vincent").is_empty() {
        assert_eq!(anonymized, 4);
    }
}

// ------------------------------------------------------------------------------------ hostile

/// Offsets of the header and content sections, as the file format lays them out.
fn content_range(bytes: &[u8]) -> (usize, std::ops::Range<usize>) {
    let size = |at: usize| u32::from_le_bytes(bytes[at..at + 4].try_into().unwrap()) as usize;
    let content_at = 8 + size(0);
    (
        content_at,
        content_at + 8..content_at + 8 + size(content_at),
    )
}

#[test]
#[ignore = "needs the replay corpus: just test-replays"]
fn a_broken_network_stream_keeps_the_header() {
    let directory = temp_dir("network");
    for path in public_replays()
        .into_iter()
        .filter(|p| name(p).starts_with("post-eac"))
    {
        let label = name(&path);
        let mut bytes = read(&path);
        let (content_at, content) = content_range(&bytes);
        // The network stream fills most of the content: this lands inside it.
        let middle = content.start + content.len() / 3;
        bytes[middle..middle + 4096]
            .iter_mut()
            .for_each(|byte| *byte = !*byte);
        let crc = boxcars::crc::calc_crc(&bytes[content.clone()]);
        bytes[content_at + 4..content_at + 8].copy_from_slice(&crc.to_le_bytes());

        let input = directory.join(&label);
        std::fs::write(&input, &bytes).unwrap();
        let out = directory.join(format!("{label}.out"));
        let header_run = parse_header(&input, &out.with_extension("json"));
        assert_eq!(
            header_run.code,
            Some(0),
            "{label}: the header must still read"
        );

        let run = parse_frames(&input, &out);
        assert!(
            matches!(run.code, Some(12 | 13)),
            "{label}: exit {:?}",
            run.code
        );
        assert!(matches!(
            error_code(&run).as_str(),
            "network_failed" | "processor_failed"
        ));
        assert!(
            !out.join("frames.parquet").exists(),
            "{label}: no partial output"
        );
    }
    std::fs::remove_dir_all(&directory).unwrap();
}

#[test]
#[ignore = "needs the replay corpus: just test-replays"]
fn broken_files_fail_cleanly_and_quote_nobody() {
    let directory = temp_dir("broken");
    let path = public_replays()
        .into_iter()
        .find(|p| name(p).starts_with("post-eac-ranked-doubles"))
        .unwrap();
    let original = read(&path);
    let replay = ParserBuilder::new(&original)
        .never_parse_network_data()
        .parse()
        .unwrap();
    let names: Vec<String> = header::extract(&replay)
        .players
        .into_iter()
        .map(|p| p.name)
        .collect();
    let input = directory.join("broken.replay");

    let check = |bytes: &[u8], label: &str, codes: &[i32]| {
        std::fs::write(&input, bytes).unwrap();
        for run in [
            parse_header(&input, &directory.join("h.json")),
            parse_frames(&input, &directory.join("out")),
        ] {
            let code = run.code.unwrap_or(-1);
            assert!(codes.contains(&code), "{label}: exit {code}");
            if code != 0 {
                assert!(
                    names
                        .iter()
                        .all(|player| !run.stderr.contains(player.as_str())),
                    "{label}"
                );
                error_code(&run);
            }
        }
    };

    for fraction in [1, 2, 5, 10, 50, 90, 99] {
        let cut = original.len() * fraction / 100;
        check(
            &original[..cut],
            &format!("truncated at {fraction} %"),
            &[10, 11],
        );
    }
    // A wrong CRC, in each section.
    let mut bytes = original.clone();
    bytes[4] ^= 0xFF;
    check(&bytes, "header CRC", &[11]);
    let (content_at, _) = content_range(&original);
    let mut bytes = original.clone();
    bytes[content_at + 4] ^= 0xFF;
    check(&bytes, "content CRC", &[11]);
    // Absurd sizes in the section headers.
    let mut bytes = original.clone();
    bytes[0..4].copy_from_slice(&u32::MAX.to_le_bytes());
    check(&bytes, "absurd header size", &[10, 11]);
    let mut bytes = original.clone();
    bytes[content_at..content_at + 4].copy_from_slice(&u32::MAX.to_le_bytes());
    check(&bytes, "absurd content size", &[11]);
    std::fs::remove_dir_all(&directory).unwrap();
}

#[test]
#[ignore = "needs the replay corpus: just test-replays"]
fn the_longest_replay_is_fast() {
    let Some(path) = replays("legacy").into_iter().find(|p| {
        let file = name(p);
        file.contains(SLOW_REPLAY) && !file.contains(" - Copie")
    }) else {
        return; // personal replay: not in CI.
    };
    let directory = temp_dir("long");
    let start = Instant::now();
    let run = parse_frames(&path, &directory);
    let elapsed = start.elapsed();
    std::fs::remove_dir_all(&directory).unwrap();
    assert_eq!(run.code, Some(0));
    assert!(elapsed.as_secs() < 10, "{elapsed:?}");
}
