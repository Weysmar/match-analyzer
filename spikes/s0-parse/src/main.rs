//! Throwaway spike for step 0 of docs/PLAN.md: one child process per replay, one JSON line per
//! replay. The output holds measurements only: no player name and no platform id is ever written.
#![forbid(unsafe_code)]

mod identity;
mod light;
mod oracle;

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::io::Write;
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::Arc;
use std::time::{Duration, Instant};

use arrow::array::{ArrayRef, BooleanArray, Float32Array, RecordBatch, UInt8Array, UInt32Array};
use arrow::datatypes::{DataType, Field, Schema};
use boxcars::{Attribute, HeaderProp, ParserBuilder, RemoteId, Replay};
use parquet::arrow::ArrowWriter;
use parquet::basic::{Compression, ZstdLevel};
use parquet::file::properties::WriterProperties;
use serde_json::{Value, json};
use subtr_actor::{
    BallFrame, BoostPadEventKind, BoostPadSize, FrameData, GameplayPhase, PlayerFrame, ReplayData,
    ReplayDataCollector, StatsCollector, StatsFrameResolution, StatsTimelineEventCollector,
};

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("probe") => probe(Path::new(&args[1])),
        Some("run") => run(&args[1], args[2].parse().expect("timeout"), &args[3..]),
        Some("stats-shape") => stats_shape(Path::new(&args[1])),
        Some("oracle") => oracle::oracle(Path::new(&args[1])),
        Some("corpus-info") => corpus_info(&args[1..]),
        Some("identity") => identity::identity(&replay_files(&args[1..])),
        Some("epic-check") => epic_check(&args[1], &args[2..]),
        Some("stages") => stages(Path::new(&args[1])),
        Some("light") => light::light(Path::new(&args[1]), args.get(2).is_none_or(|a| a != "--no-compare")),
        _ => {
            eprintln!("usage: s0-parse run <out.jsonl> <timeout_s> <dir|file>... | probe <file> | stats-shape <file>");
            std::process::exit(2);
        }
    }
}

// ------------------------------------------------------------------------------------- driver

fn replay_files(inputs: &[String]) -> Vec<PathBuf> {
    let mut files = Vec::new();
    for input in inputs {
        let path = PathBuf::from(input);
        if path.is_dir() {
            for entry in std::fs::read_dir(&path).expect("read dir").flatten() {
                if entry.path().extension().is_some_and(|e| e == "replay") {
                    files.push(entry.path());
                }
            }
        } else {
            files.push(path);
        }
    }
    files.sort();
    files
}

fn run(out: &str, timeout_s: u64, inputs: &[String]) {
    let exe = std::env::current_exe().expect("current exe");
    let mut output = std::fs::File::create(out).expect("create output");
    let files = replay_files(inputs);
    for (index, file) in files.iter().enumerate() {
        let mut child = Command::new(&exe)
            .arg("probe")
            .arg(file)
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .expect("spawn");
        let start = Instant::now();
        let status = loop {
            if let Some(status) = child.try_wait().expect("wait") {
                break Some(status);
            }
            if start.elapsed() > Duration::from_secs(timeout_s) {
                let _ = child.kill();
                let _ = child.wait();
                break None;
            }
            std::thread::sleep(Duration::from_millis(20));
        };
        let wall_ms = start.elapsed().as_millis() as u64;
        let stdout = std::io::read_to_string(child.stdout.take().unwrap()).unwrap_or_default();
        let group = file.parent().and_then(Path::file_name).map(|n| n.to_string_lossy().into_owned());
        let mut line: Value = serde_json::from_str(stdout.trim()).unwrap_or_else(|_| json!({}));
        line["group"] = json!(group);
        line["file"] = json!(file.file_name().map(|n| n.to_string_lossy().into_owned()));
        line["wall_ms"] = json!(wall_ms);
        line["exit"] = json!(status.and_then(|s| s.code()));
        line["killed_by_timeout"] = json!(status.is_none());
        writeln!(output, "{line}").expect("write");
        eprintln!("[{}/{}] {} {} ms", index + 1, files.len(), line["file"], wall_ms);
    }
}

/// T0.2: how varied is a set of replays? One line per replay, then how many replays each player
/// appears in, by platform. Ids are only compared in memory: no name and no id is printed.
fn corpus_info(inputs: &[String]) {
    let mut seen: HashMap<String, (usize, &'static str)> = HashMap::new();
    let mut results: Vec<(Vec<String>, Vec<String>, i64, i64)> = Vec::new();
    let files = replay_files(inputs);
    for file in &files {
        let bytes = std::fs::read(file).expect("read");
        let label = file.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
        let Ok(replay) = ParserBuilder::new(&bytes).must_parse_network_data().parse() else {
            println!("{label}: network failed");
            continue;
        };
        let props = &replay.properties;
        let int = |key: &str| match prop(props, key) {
            Some(HeaderProp::Int(i)) => *i as i64,
            _ => 0,
        };
        let text = |key: &str| match prop(props, key) {
            Some(HeaderProp::Str(s) | HeaderProp::Name(s)) => s.clone(),
            _ => "?".to_owned(),
        };
        let mut overtime = false;
        if let Some(frames) = replay.network_frames.as_ref() {
            for frame in &frames.frames {
                for update in &frame.updated_actors {
                    if matches!(update.attribute, Attribute::Boolean(true))
                        && replay.objects.get(update.object_id.0 as usize).is_some_and(|o| o == "TAGame.GameEvent_Soccar_TA:bOverTime")
                    {
                        overtime = true;
                    }
                }
            }
        }
        let (blue, orange) = (int("Team0Score"), int("Team1Score"));
        let primary = prop(props, "PrimaryPlayerTeam").map(|_| int("PrimaryPlayerTeam"));
        let result = match primary {
            Some(0) if blue > orange => "win",
            Some(1) if orange > blue => "win",
            Some(_) => "loss",
            None => "?",
        };
        let meta = subtr_actor::ReplayProcessor::new(&replay).ok().and_then(|mut p| p.process_and_get_replay_meta().ok());
        let (playlist, players) = meta.as_ref().map_or((None, 0), |m| (m.game_type.playlist_id, m.player_count()));
        let mut kinds: BTreeMap<&str, u32> = BTreeMap::new();
        if let Some(meta) = &meta {
            let ids = |team: &[subtr_actor::PlayerInfo]| team.iter().map(|p| format!("{:?}", p.remote_id)).collect::<Vec<_>>();
            results.push((ids(&meta.team_zero), ids(&meta.team_one), blue, orange));
            for player in meta.player_order() {
                let kind = remote_kind(&player.remote_id);
                *kinds.entry(kind).or_default() += 1;
                seen.entry(format!("{:?}", player.remote_id)).or_insert((0, kind)).0 += 1;
            }
        }
        println!(
            "{} date={} build={} net={:?} type={} playlist={playlist:?} team_size={} players={players} map={} score={blue}-{orange} overtime={overtime} recorder={result} kinds={kinds:?}",
            &label[..label.len().min(12)], text("Date"), text("BuildVersion"), replay.net_version, text("MatchType"), int("TeamSize"), text("MapName")
        );
    }
    let mut recurring: Vec<(usize, &str)> = seen.values().map(|(n, kind)| (*n, *kind)).filter(|(n, _)| *n >= 2).collect();
    recurring.sort_unstable_by(|a, b| b.cmp(a));
    println!("replays: {}; players seen in 2 or more replays (count, platform): {recurring:?}", files.len());
    if let Some((top, _)) = seen.iter().max_by_key(|(_, (n, _))| *n) {
        let (mut wins, mut losses) = (0, 0);
        for (zero, one, blue, orange) in &results {
            let won = (zero.contains(top) && blue > orange) || (one.contains(top) && orange > blue);
            let played = zero.contains(top) || one.contains(top);
            wins += usize::from(played && won);
            losses += usize::from(played && !won);
        }
        println!("most frequent player: {wins} wins, {losses} losses");
    }
}

/// T0.7: in how many replays does this Epic account id appear on the network? Prints counts only.
fn epic_check(account_id: &str, inputs: &[String]) {
    let wanted = account_id.trim().to_ascii_lowercase();
    let (mut replays, mut matches, mut with_epic) = (0, 0, 0);
    for file in replay_files(inputs) {
        let Ok(bytes) = std::fs::read(&file) else { continue };
        let Ok(replay) = ParserBuilder::new(&bytes).must_parse_network_data().parse() else { continue };
        let Ok(mut processor) = subtr_actor::ReplayProcessor::new(&replay) else { continue };
        let Ok(meta) = processor.process_and_get_replay_meta() else { continue };
        replays += 1;
        let epic: Vec<String> = meta
            .player_order()
            .filter_map(|p| match &p.remote_id {
                RemoteId::Epic(id) => Some(id.to_ascii_lowercase()),
                _ => None,
            })
            .collect();
        with_epic += usize::from(!epic.is_empty());
        matches += usize::from(epic.contains(&wanted));
    }
    println!("replays read: {replays}, with an Epic player: {with_epic}, with this account id: {matches}");
}

/// Prints each stage as it starts, to find where a replay gets stuck.
fn stages(path: &Path) {
    let bytes = std::fs::read(path).expect("read replay");
    let start = Instant::now();
    let say = |stage: &str| eprintln!("{:>8} ms  rss {:>7} KiB  {stage}", start.elapsed().as_millis(), peak_rss_kb());
    say("header");
    let header = ParserBuilder::new(&bytes).never_parse_network_data().on_error_check_crc().parse();
    say(if header.is_ok() { "header ok, network" } else { "header failed, network" });
    let replay = ParserBuilder::new(&bytes).must_parse_network_data().always_check_crc().parse();
    let Ok(replay) = replay else {
        say("network failed");
        return;
    };
    say(&format!("network ok, {} frames, data", replay.network_frames.as_ref().map_or(0, |f| f.frames.len())));
    let data = ReplayDataCollector::new().get_replay_data(&replay);
    say(if data.is_ok() { "data ok, scaffold" } else { "data failed, scaffold" });
    let scaffold = StatsTimelineEventCollector::new()
        .with_frame_resolution(StatsFrameResolution::EveryFrame)
        .get_replay_stats_timeline_scaffold(&replay);
    say(if scaffold.is_ok() { "scaffold ok, stats" } else { "scaffold failed, stats" });
    let stats = StatsCollector::new().get_stats(&replay);
    say(if stats.is_ok() { "stats ok" } else { "stats failed" });
}

// ---------------------------------------------------------------------------------------- probe

/// Peak resident memory of this process so far, in KiB.
fn peak_rss_kb() -> u64 {
    std::fs::read_to_string("/proc/self/status")
        .ok()
        .and_then(|status| {
            status.lines().find(|l| l.starts_with("VmHWM:")).and_then(|l| {
                l.split_whitespace().nth(1).and_then(|v| v.parse().ok())
            })
        })
        .unwrap_or(0)
}

/// Errors can quote player names (subtr-actor formats whole header entries): keep the shape only.
fn safe_error(text: &str) -> String {
    let head: String = text.chars().take_while(|c| !matches!(c, '"' | '\'' | '{' | '[' | '(')).take(70).collect();
    head.trim().to_owned()
}

fn timed<T>(f: impl FnOnce() -> T) -> (T, u64) {
    let start = Instant::now();
    let value = f();
    (value, start.elapsed().as_millis() as u64)
}

fn probe(path: &Path) {
    std::panic::set_hook(Box::new(|_| {}));
    let bytes = std::fs::read(path).expect("read replay");
    let mut report = json!({ "size": bytes.len() });

    let (header, header_ms) = timed(|| {
        ParserBuilder::new(&bytes).never_parse_network_data().on_error_check_crc().parse()
    });
    report["header_ms"] = json!(header_ms);
    report["rss_header_kb"] = json!(peak_rss_kb());
    match &header {
        Ok(replay) => {
            report["header_ok"] = json!(true);
            report["header"] = header_info(replay);
        }
        Err(error) => {
            report["header_ok"] = json!(false);
            report["header_error"] = json!(safe_error(&error.to_string()));
        }
    }

    let (network, network_ms) = timed(|| {
        ParserBuilder::new(&bytes).must_parse_network_data().always_check_crc().parse()
    });
    report["network_ms"] = json!(network_ms);
    report["rss_network_kb"] = json!(peak_rss_kb());
    let replay = match network {
        Ok(replay) => {
            report["network_ok"] = json!(true);
            replay
        }
        Err(error) => {
            report["network_ok"] = json!(false);
            report["network_error"] = json!(safe_error(&error.to_string()));
            println!("{report}");
            return;
        }
    };
    report["anonymization"] = anonymization_info(&replay);

    let (data, data_ms) = timed(|| {
        catch_unwind(AssertUnwindSafe(|| ReplayDataCollector::new().get_replay_data(&replay)))
    });
    report["data_ms"] = json!(data_ms);
    report["rss_data_kb"] = json!(peak_rss_kb());
    let data = match data {
        Ok(Ok(data)) => {
            report["data_ok"] = json!(true);
            data
        }
        Ok(Err(error)) => {
            report["data_ok"] = json!(false);
            report["data_error"] = json!(safe_error(&format!("{:?}", error.variant)));
            println!("{report}");
            return;
        }
        Err(_) => {
            report["data_ok"] = json!(false);
            report["data_error"] = json!("panic");
            println!("{report}");
            return;
        }
    };

    let (phases, phases_ms) = timed(|| {
        catch_unwind(AssertUnwindSafe(|| {
            StatsTimelineEventCollector::new()
                .with_frame_resolution(StatsFrameResolution::EveryFrame)
                .get_replay_stats_timeline_scaffold(&replay)
                .map(|t| {
                    t.frames
                        .iter()
                        .map(|f| (f.time.to_bits(), (f.gameplay_phase, f.dt)))
                        .collect::<HashMap<u32, (GameplayPhase, f32)>>()
                })
        }))
    });
    report["phases_ms"] = json!(phases_ms);
    report["rss_phases_kb"] = json!(peak_rss_kb());
    let phases = match phases {
        Ok(Ok(map)) => {
            report["phases_ok"] = json!(true);
            map
        }
        other => {
            report["phases_ok"] = json!(false);
            report["phases_error"] = json!(match other {
                Ok(Err(error)) => safe_error(&format!("{:?}", error.variant)),
                _ => "panic".to_owned(),
            });
            HashMap::new()
        }
    };

    report["identity"] = identity_info(&data);
    report["measures"] = measures(&data, &phases);
    report["pads"] = pads_info(&data);
    report["events"] = json!({
        "goals": data.goal_events.len(),
        "goals_with_player": data.goal_events.iter().filter(|g| g.player.is_some()).count(),
        "demolitions": data.demolish_infos.len(),
        "stat_events": data.player_stat_events.len(),
        "touches": data.touch_events.len(),
    });
    report["game_type"] = json!({
        "class": replay.game_type,
        "kind": format!("{:?}", data.meta.game_type.game_type),
        "playlist_id": data.meta.game_type.playlist_id,
        "match_type": data.meta.game_type.header_match_type,
    });

    let phase_lookup = |time: f32| phases.get(&time.to_bits()).map(|p| p.0).unwrap_or_default();
    let (parquet_all, parquet_ms) = timed(|| parquet_size(&data.frame_data, 1, &phase_lookup));
    let parquet_half = parquet_size(&data.frame_data, 2, &phase_lookup);
    report["parquet"] = json!({ "bytes_every_frame": parquet_all, "bytes_every_2nd_frame": parquet_half, "ms": parquet_ms });
    report["rss_parquet_kb"] = json!(peak_rss_kb());

    let (stats, stats_ms) = timed(|| {
        catch_unwind(AssertUnwindSafe(|| StatsCollector::new().get_stats(&replay).is_ok())).unwrap_or(false)
    });
    report["stats_ok"] = json!(stats);
    report["stats_ms"] = json!(stats_ms);
    report["rss_stats_kb"] = json!(peak_rss_kb());
    println!("{report}");
}

// --------------------------------------------------------------------------------------- header

fn prop<'a>(props: &'a [(String, HeaderProp)], key: &str) -> Option<&'a HeaderProp> {
    props.iter().find(|(k, _)| k == key).map(|(_, v)| v)
}

fn prop_kind(value: &HeaderProp) -> &'static str {
    match value {
        HeaderProp::Array(_) => "array",
        HeaderProp::Bool(_) => "bool",
        HeaderProp::Byte { .. } => "byte",
        HeaderProp::Float(_) => "float",
        HeaderProp::Int(_) => "int",
        HeaderProp::Name(_) => "name",
        HeaderProp::QWord(_) => "qword",
        HeaderProp::Str(_) => "str",
        _ => "other",
    }
}

fn header_info(replay: &Replay) -> Value {
    let props = &replay.properties;
    let text = |key: &str| prop(props, key).and_then(|v| match v {
        HeaderProp::Str(s) | HeaderProp::Name(s) => Some(s.clone()),
        _ => None,
    });
    let int = |key: &str| prop(props, key).and_then(|v| match v {
        HeaderProp::Int(i) => Some(*i as i64),
        HeaderProp::QWord(q) => Some(*q as i64),
        _ => None,
    });
    let float = |key: &str| prop(props, key).and_then(|v| match v {
        HeaderProp::Float(f) => Some(*f),
        _ => None,
    });
    let keys: BTreeMap<String, &str> = props.iter().map(|(k, v)| (k.clone(), prop_kind(v))).collect();

    let mut players = Vec::new();
    let mut player_keys = BTreeSet::new();
    if let Some(HeaderProp::Array(entries)) = prop(props, "PlayerStats") {
        for entry in entries {
            for (k, _) in entry {
                player_keys.insert(k.clone());
            }
            let platform = prop(entry, "Platform").and_then(|v| match v {
                HeaderProp::Byte { value, .. } => value.clone(),
                _ => None,
            });
            let online_id_zero = matches!(prop(entry, "OnlineID"), Some(HeaderProp::QWord(0)));
            let bot = matches!(prop(entry, "bBot"), Some(HeaderProp::Bool(true)));
            let player_id_keys = prop(entry, "PlayerID").map(prop_kind);
            players.push(json!({ "platform": platform, "online_id_zero": online_id_zero, "bot": bot, "player_id": player_id_keys }));
        }
    }
    let mut goal_keys = BTreeSet::new();
    let mut goals = 0;
    if let Some(HeaderProp::Array(entries)) = prop(props, "Goals") {
        goals = entries.len();
        for entry in entries {
            for (k, _) in entry {
                goal_keys.insert(k.clone());
            }
        }
    }
    json!({
        "version": [replay.major_version, replay.minor_version, replay.net_version],
        "class": replay.game_type,
        "build_version": text("BuildVersion"),
        "build_id": int("BuildID"),
        "changelist": int("Changelist"),
        "date": text("Date"),
        "match_start_epoch": int("MatchStartEpoch"),
        "has_match_guid": prop(props, "MatchGUID").is_some(),
        "match_guid_len": text("MatchGUID").map(|s| s.len()),
        "has_id": prop(props, "Id").is_some(),
        "num_frames": int("NumFrames"),
        "record_fps": float("RecordFPS"),
        "team_size": int("TeamSize"),
        "match_type": text("MatchType"),
        "map": text("MapName"),
        "header_goals": goals,
        "goal_keys": goal_keys,
        "player_keys": player_keys,
        "players": players,
        "keys": keys,
    })
}

// ------------------------------------------------------------------------------------- identity

fn remote_kind(id: &RemoteId) -> &'static str {
    match id {
        RemoteId::Steam(_) => "steam",
        RemoteId::Epic(_) => "epic",
        RemoteId::Xbox(_) => "xbox",
        RemoteId::PlayStation(_) => "playstation",
        RemoteId::PsyNet(_) => "psynet",
        RemoteId::Switch(_) => "switch",
        RemoteId::SplitScreen(_) => "splitscreen",
        RemoteId::QQ(_) => "qq",
        _ => "other",
    }
}

fn identity_info(data: &ReplayData) -> Value {
    let mut kinds: BTreeMap<&str, u32> = BTreeMap::new();
    let mut names = BTreeSet::new();
    let mut duplicates = 0;
    let mut epic_hex32 = 0;
    let mut epic_other = 0;
    let mut steam_shape = 0;
    let mut without_header_stats = 0;
    let mut players = 0;
    for player in data.meta.player_order() {
        players += 1;
        *kinds.entry(remote_kind(&player.remote_id)).or_default() += 1;
        if !names.insert(player.name.clone()) {
            duplicates += 1;
        }
        if player.stats.is_none() {
            without_header_stats += 1;
        }
        match &player.remote_id {
            RemoteId::Epic(id) => {
                if id.len() == 32 && id.chars().all(|c| c.is_ascii_hexdigit()) {
                    epic_hex32 += 1;
                } else {
                    epic_other += 1;
                }
            }
            RemoteId::Steam(id) if id.to_string().starts_with("7656119") => steam_shape += 1,
            _ => {}
        }
    }
    json!({
        "players": players,
        "kinds": kinds,
        "duplicate_names": duplicates,
        "epic_id_32_hex": epic_hex32,
        "epic_id_other_shape": epic_other,
        "steam_id64_shape": steam_shape,
        "players_without_header_stats": without_header_stats,
        "team_zero": data.meta.team_zero.len(),
        "team_one": data.meta.team_one.len(),
    })
}

fn anonymization_info(replay: &Replay) -> Value {
    let Some(frames) = replay.network_frames.as_ref() else {
        return json!(null);
    };
    let mut seen: BTreeMap<&str, u32> = BTreeMap::new();
    let mut anon_true = 0;
    let mut anon_names = BTreeSet::new();
    let mut pri_names = BTreeSet::new();
    let mut puid = 0;
    for frame in &frames.frames {
        for update in &frame.updated_actors {
            let Some(object) = replay.objects.get(update.object_id.0 as usize) else {
                continue;
            };
            match object.as_str() {
                "TAGame.PRI_TA:bAnonymizeToOpponents" | "TAGame.PRI_TA:bAnonymizeToTeammates" => {
                    *seen.entry("flag_updates").or_default() += 1;
                    if matches!(update.attribute, Attribute::Boolean(true)) {
                        anon_true += 1;
                    }
                }
                "TAGame.PRI_TA:AnonymizedName" => {
                    if let Attribute::String(name) = &update.attribute {
                        anon_names.insert(name.clone());
                    }
                }
                "Engine.PlayerReplicationInfo:PlayerName" => {
                    if let Attribute::String(name) = &update.attribute {
                        pri_names.insert(name.clone());
                    }
                }
                "TAGame.PRI_TA:EpicPUID" => puid += 1,
                _ => {}
            }
        }
    }
    json!({
        "flag_updates": seen.get("flag_updates").copied().unwrap_or(0),
        "flag_true": anon_true,
        "anonymized_names": anon_names.len(),
        "anonymized_names_equal_to_player_name": anon_names.intersection(&pri_names).count(),
        "epic_puid_updates": puid,
    })
}

// ------------------------------------------------------------------------------------- measures

#[derive(Clone, Copy)]
struct Extent {
    min: f32,
    max: f32,
}

impl Extent {
    fn new() -> Self {
        Self { min: f32::INFINITY, max: f32::NEG_INFINITY }
    }
    fn add(&mut self, v: f32) {
        self.min = self.min.min(v);
        self.max = self.max.max(v);
    }
    fn json(self) -> Value {
        if self.min.is_finite() { json!([self.min, self.max]) } else { json!(null) }
    }
}

fn median(values: &mut [f32]) -> Option<f32> {
    if values.is_empty() {
        return None;
    }
    values.sort_by(f32::total_cmp);
    Some(values[values.len() / 2])
}

fn measures(data: &ReplayData, phases: &HashMap<u32, (GameplayPhase, f32)>) -> Value {
    let fd = &data.frame_data;
    let meta = &fd.metadata_frames;
    let frames = meta.len();
    let mut phase_counts: BTreeMap<String, u64> = BTreeMap::new();
    let mut aligned = 0u64;
    let phase_at: Vec<GameplayPhase> = meta
        .iter()
        .map(|m| match phases.get(&m.time.to_bits()) {
            Some(p) => {
                aligned += 1;
                p.0
            }
            None => GameplayPhase::Unknown,
        })
        .collect();
    for p in &phase_at {
        *phase_counts.entry(format!("{p:?}")).or_default() += 1;
    }

    let (mut bx, mut by, mut bz) = (Extent::new(), Extent::new(), Extent::new());
    for (i, f) in fd.ball_data.frames().iter().enumerate() {
        if i < frames && phase_at[i] == GameplayPhase::ActivePlay {
            if let BallFrame::Data { rigid_body } = f {
                bx.add(rigid_body.location.x);
                by.add(rigid_body.location.y);
                bz.add(rigid_body.location.z);
            }
        }
    }

    let (mut cx, mut cy, mut cz) = (Extent::new(), Extent::new(), Extent::new());
    let mut boost = Extent::new();
    let (mut boost_zero, mut boost_full, mut boost_samples) = (0u64, 0u64, 0u64);
    let mut kickoff_boost = Vec::new();
    let mut speed_bins: BTreeMap<i32, u64> = BTreeMap::new();
    let mut speed_max = 0f32;
    let (mut samples, mut no_velocity, mut z_le_20, mut bad_quat) = (0u64, 0u64, 0u64, 0u64);
    let mut grounded_z = Vec::new();
    let mut empty_active = 0u64;
    let (mut t0_y, mut t0_n, mut t1_y, mut t1_n) = (0f64, 0u64, 0f64, 0u64);
    let mut team_unknown = 0u64;
    for (_, player) in &fd.players {
        for (i, f) in player.frames().iter().enumerate() {
            if i >= frames {
                break;
            }
            let phase = phase_at[i];
            let PlayerFrame::Data { rigid_body, boost_amount, is_team_0, .. } = f else {
                if phase == GameplayPhase::ActivePlay {
                    empty_active += 1;
                }
                continue;
            };
            if phase == GameplayPhase::KickoffCountdown {
                kickoff_boost.push(*boost_amount);
                match is_team_0 {
                    Some(true) => {
                        t0_y += rigid_body.location.y as f64;
                        t0_n += 1;
                    }
                    Some(false) => {
                        t1_y += rigid_body.location.y as f64;
                        t1_n += 1;
                    }
                    None => team_unknown += 1,
                }
            }
            if phase != GameplayPhase::ActivePlay {
                continue;
            }
            samples += 1;
            cx.add(rigid_body.location.x);
            cy.add(rigid_body.location.y);
            cz.add(rigid_body.location.z);
            boost.add(*boost_amount);
            boost_samples += 1;
            if *boost_amount <= 1.0 {
                boost_zero += 1;
            }
            if *boost_amount >= 254.0 {
                boost_full += 1;
            }
            let r = rigid_body.rotation;
            let norm = (r.x * r.x + r.y * r.y + r.z * r.z + r.w * r.w).sqrt();
            if (norm - 1.0).abs() > 0.01 {
                bad_quat += 1;
            }
            if rigid_body.location.z <= 20.0 {
                z_le_20 += 1;
                grounded_z.push(rigid_body.location.z);
            }
            match rigid_body.linear_velocity {
                Some(v) => {
                    let speed = (v.x * v.x + v.y * v.y + v.z * v.z).sqrt();
                    speed_max = speed_max.max(speed);
                    if speed >= 2000.0 {
                        *speed_bins.entry(((speed / 20.0).floor() as i32) * 20).or_default() += 1;
                    }
                }
                None => no_velocity += 1,
            }
        }
    }

    // Which side does each team score on? The ball is deep in that half on the frame of the goal.
    let mut goals_team0_pos = 0;
    let mut goals_team0_neg = 0;
    let mut goals_team1_pos = 0;
    let mut goals_team1_neg = 0;
    let times: Vec<f32> = meta.iter().map(|m| m.time).collect();
    let mut goal_ball_y = Vec::new();
    for goal in &data.goal_events {
        let i = times.partition_point(|t| *t <= goal.time).saturating_sub(1);
        if let Some(BallFrame::Data { rigid_body }) = fd.ball_data.frames().get(i) {
            let y = rigid_body.location.y;
            goal_ball_y.push(y.abs());
            match (goal.scoring_team_is_team_0, y > 0.0) {
                (true, true) => goals_team0_pos += 1,
                (true, false) => goals_team0_neg += 1,
                (false, true) => goals_team1_pos += 1,
                (false, false) => goals_team1_neg += 1,
            }
        }
    }

    // Do demolitions show up as empty player frames, and for how long?
    let by_id: HashMap<String, usize> = fd
        .players
        .iter()
        .enumerate()
        .map(|(i, (id, _))| (format!("{id:?}"), i))
        .collect();
    let (mut demo_followed_by_empty, mut demo_not_empty, mut demo_unknown_victim) = (0, 0, 0);
    let mut demo_run_s = Vec::new();
    let mut demo_empty_indices: Vec<(usize, usize)> = Vec::new();
    for demo in &data.demolish_infos {
        let Some(&player) = by_id.get(&format!("{:?}", demo.victim)) else {
            demo_unknown_victim += 1;
            continue;
        };
        let start = times.partition_point(|t| *t < demo.time);
        let pf = fd.players[player].1.frames();
        let window_end = (start + 30).min(pf.len());
        match (start..window_end).find(|i| matches!(pf[*i], PlayerFrame::Empty)) {
            Some(first) => {
                demo_followed_by_empty += 1;
                let mut end = first;
                while end < pf.len() && matches!(pf[end], PlayerFrame::Empty) {
                    end += 1;
                }
                if end < times.len() {
                    demo_run_s.push(times[end] - times[first]);
                }
                demo_empty_indices.push((player, first));
            }
            None => demo_not_empty += 1,
        }
    }
    // Empty runs during active play that no demolition explains.
    let mut unexplained_runs = 0;
    for (p, (_, player)) in fd.players.iter().enumerate() {
        let pf = player.frames();
        let mut i = 0;
        while i < pf.len().min(frames) {
            if matches!(pf[i], PlayerFrame::Empty) && phase_at[i] == GameplayPhase::ActivePlay {
                let start = i;
                while i < pf.len().min(frames) && matches!(pf[i], PlayerFrame::Empty) {
                    i += 1;
                }
                if !demo_empty_indices.iter().any(|(dp, first)| *dp == p && first.abs_diff(start) <= 30) {
                    unexplained_runs += 1;
                }
            } else {
                i += 1;
            }
        }
    }

    let duration = fd.duration();
    json!({
        "frames": frames,
        "duration_s": duration,
        "effective_fps": if duration > 0.0 { frames as f32 / duration } else { 0.0 },
        "phase_aligned_frames": aligned,
        "phase_counts": phase_counts,
        "ball": { "x": bx.json(), "y": by.json(), "z": bz.json() },
        "car": { "x": cx.json(), "y": cy.json(), "z": cz.json() },
        "car_samples": samples,
        "no_velocity_samples": no_velocity,
        "bad_quaternions": bad_quat,
        "speed_max": speed_max,
        "speed_bins_from_2000": speed_bins,
        "z_le_20": z_le_20,
        "grounded_z_median": median(&mut grounded_z),
        "boost": boost.json(),
        "boost_samples": boost_samples,
        "boost_le_1": boost_zero,
        "boost_ge_254": boost_full,
        "kickoff_boost_median": median(&mut kickoff_boost),
        "kickoff_mean_y": { "team0": if t0_n > 0 { Some(t0_y / t0_n as f64) } else { None }, "team1": if t1_n > 0 { Some(t1_y / t1_n as f64) } else { None }, "team_unknown": team_unknown },
        "goals_side": { "team0_y_pos": goals_team0_pos, "team0_y_neg": goals_team0_neg, "team1_y_pos": goals_team1_pos, "team1_y_neg": goals_team1_neg },
        "goal_ball_abs_y_median": median(&mut goal_ball_y),
        "empty_player_frames_active": empty_active,
        "demolitions": { "followed_by_empty": demo_followed_by_empty, "not_empty": demo_not_empty, "unknown_victim": demo_unknown_victim, "empty_run_s_median": median(&mut demo_run_s), "unexplained_empty_runs": unexplained_runs },
    })
}

fn pads_info(data: &ReplayData) -> Value {
    let known: HashMap<&str, BoostPadSize> = data
        .boost_pads
        .iter()
        .filter_map(|p| p.pad_id.as_deref().map(|id| (id, p.size)))
        .collect();
    let (mut picked, mut with_player, mut resolved, mut big, mut small) = (0, 0, 0, 0, 0);
    let mut available = 0;
    for event in &data.boost_pad_events {
        match event.kind {
            BoostPadEventKind::PickedUp { .. } => {
                picked += 1;
                if event.player.is_some() {
                    with_player += 1;
                }
                match known.get(event.pad_id.as_str()) {
                    Some(BoostPadSize::Big) => {
                        resolved += 1;
                        big += 1;
                    }
                    Some(BoostPadSize::Small) => {
                        resolved += 1;
                        small += 1;
                    }
                    None => {}
                }
            }
            BoostPadEventKind::Available => available += 1,
        }
    }
    json!({
        "pads": data.boost_pads.len(),
        "pads_with_id": known.len(),
        "picked_up": picked,
        "picked_up_with_player": with_player,
        "picked_up_resolved": resolved,
        "big": big,
        "small": small,
        "available_events": available,
    })
}

// -------------------------------------------------------------------------------------- parquet

fn phase_code(phase: GameplayPhase) -> u8 {
    match phase {
        GameplayPhase::KickoffCountdown => 1,
        GameplayPhase::KickoffWaitingForTouch => 2,
        GameplayPhase::ActivePlay => 3,
        GameplayPhase::PostGoal => 4,
        _ => 0,
    }
}

/// Size of the long format of docs/PLAN.md (one row per frame and player), every `step`-th frame.
fn parquet_size(fd: &FrameData, step: usize, phase_at: &dyn Fn(f32) -> GameplayPhase) -> usize {
    const FLOATS: [&str; 20] = [
        "time_s", "dt_s", "ball_x", "ball_y", "ball_z", "ball_vx", "ball_vy", "ball_vz", "x", "y", "z",
        "qx", "qy", "qz", "qw", "vx", "vy", "vz", "boost", "ball_speed_unused",
    ];
    let mut floats: Vec<Vec<Option<f32>>> = vec![Vec::new(); FLOATS.len() - 1];
    let mut frame_col = Vec::new();
    let (mut phase_col, mut player_col, mut team_col) = (Vec::new(), Vec::new(), Vec::new());
    let mut flags: Vec<Vec<bool>> = vec![Vec::new(); 6];
    let meta = &fd.metadata_frames;
    for i in (0..meta.len()).step_by(step) {
        let time = meta[i].time;
        let dt = if i + step < meta.len() { meta[i + step].time - time } else { 0.0 };
        let ball = fd.ball_data.frames().get(i);
        let (b, bv) = match ball {
            Some(BallFrame::Data { rigid_body }) => (Some(rigid_body.location), rigid_body.linear_velocity),
            _ => (None, None),
        };
        for (p, (_, player)) in fd.players.iter().enumerate() {
            let frame = player.frames().get(i).unwrap_or(&PlayerFrame::Empty);
            frame_col.push(i as u32);
            phase_col.push(phase_code(phase_at(time)));
            player_col.push(p as u8);
            let mut row: [Option<f32>; 19] = [None; 19];
            row[0] = Some(time);
            row[1] = Some(dt);
            if let Some(b) = b {
                (row[2], row[3], row[4]) = (Some(b.x), Some(b.y), Some(b.z));
            }
            if let Some(v) = bv {
                (row[5], row[6], row[7]) = (Some(v.x), Some(v.y), Some(v.z));
            }
            let mut bits = [false; 6];
            let mut team = 0u8;
            if let PlayerFrame::Data { rigid_body, boost_amount, boost_active, jump_active, double_jump_active, dodge_active, is_team_0, .. } = frame {
                let l = rigid_body.location;
                let q = rigid_body.rotation;
                (row[8], row[9], row[10]) = (Some(l.x), Some(l.y), Some(l.z));
                (row[11], row[12], row[13], row[14]) = (Some(q.x), Some(q.y), Some(q.z), Some(q.w));
                if let Some(v) = rigid_body.linear_velocity {
                    (row[15], row[16], row[17]) = (Some(v.x), Some(v.y), Some(v.z));
                }
                row[18] = Some(boost_amount * 100.0 / 255.0);
                bits = [true, *boost_active, *jump_active, *double_jump_active, *dodge_active, false];
                team = u8::from(*is_team_0 == Some(false));
            }
            team_col.push(team);
            for (c, v) in floats.iter_mut().zip(row) {
                c.push(v);
            }
            for (c, v) in flags.iter_mut().zip(bits) {
                c.push(v);
            }
        }
    }
    let mut fields = vec![
        Field::new("frame", DataType::UInt32, false),
        Field::new("phase", DataType::UInt8, false),
        Field::new("player_idx", DataType::UInt8, false),
        Field::new("team", DataType::UInt8, false),
    ];
    let mut columns: Vec<ArrayRef> = vec![
        Arc::new(UInt32Array::from(frame_col)),
        Arc::new(UInt8Array::from(phase_col)),
        Arc::new(UInt8Array::from(player_col)),
        Arc::new(UInt8Array::from(team_col)),
    ];
    for (name, values) in FLOATS.iter().zip(floats) {
        fields.push(Field::new(*name, DataType::Float32, true));
        columns.push(Arc::new(Float32Array::from(values)));
    }
    for (name, values) in ["present", "boost_active", "jumped", "double_jumped", "dodged", "demolished"].iter().zip(flags) {
        fields.push(Field::new(*name, DataType::Boolean, false));
        columns.push(Arc::new(BooleanArray::from(values)));
    }
    let schema = Arc::new(Schema::new(fields));
    let batch = RecordBatch::try_new(schema.clone(), columns).expect("batch");
    let props = WriterProperties::builder()
        .set_compression(Compression::ZSTD(ZstdLevel::try_new(3).expect("level")))
        .build();
    let mut out = Vec::new();
    let mut writer = ArrowWriter::try_new(&mut out, schema, Some(props)).expect("writer");
    writer.write(&batch).expect("write");
    writer.close().expect("close");
    out.len()
}

// ---------------------------------------------------------------------------------- stats shape

/// Prints the structure of the aggregate stats with names and ids removed: keys and number types.
fn stats_shape(path: &Path) {
    let bytes = std::fs::read(path).expect("read replay");
    let replay = ParserBuilder::new(&bytes).must_parse_network_data().parse().expect("parse");
    let stats = StatsCollector::new().get_stats(&replay).expect("stats");
    let value = serde_json::to_value(&stats).expect("json");
    fn shape(value: &Value, depth: usize) -> Value {
        match value {
            Value::Object(map) if depth > 0 => {
                Value::Object(map.iter().map(|(k, v)| (k.clone(), shape(v, depth - 1))).collect())
            }
            Value::Object(map) => json!(format!("object({})", map.len())),
            Value::Array(items) => match items.first() {
                Some(first) if depth > 0 => json!([format!("len={}", items.len()), shape(first, depth - 1)]),
                _ => json!(format!("array({})", items.len())),
            },
            Value::String(_) => json!("<string>"),
            other => other.clone(),
        }
    }
    let modules = value.get("modules").cloned().unwrap_or(json!({}));
    let wanted = ["boost", "movement", "positioning", "demo"];
    let picked: serde_json::Map<String, Value> = wanted
        .iter()
        .filter_map(|m| modules.get(*m).map(|v| ((*m).to_owned(), shape(v, 3))))
        .collect();
    println!("{}", serde_json::to_string_pretty(&json!({ "top": value.as_object().map(|o| o.keys().cloned().collect::<Vec<_>>()), "modules": picked })).expect("print"));
}
