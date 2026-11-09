//! `rl-oracle`: subtr-actor's own statistics for one replay, per player, in the order of the
//! roster that `rl-parse` writes. A reference for the tests and the oracle report only: it is
//! never built into the image, and `StatsCollector` stays out of production (section 6 of
//! CLAUDE.md).
//!
//! Only numbers come out. Player ids are used to match rows, then dropped.
//!
//! Output: `players` (one row per roster player: its team, then the numeric fields of each
//! module in `MODULES`, and the total of its `player_possession` spans), and `possession`, the
//! team possession times of the match.

use std::panic::{AssertUnwindSafe, catch_unwind};
use std::process::ExitCode;

use rl_parse::frames;
use serde_json::{Map, Value, json};
use subtr_actor::{ReplayDataCollector, StatsCollector};

const MODULES: [&str; 5] = ["boost", "movement", "positioning", "demo", "touch"];

/// The numeric fields of one player's row in a stats module, and nothing else.
fn numbers(stats: &Value) -> Value {
    let kept: Map<String, Value> = stats
        .as_object()
        .map(|fields| {
            fields
                .iter()
                .filter(|(_, value)| value.is_number())
                .map(|(name, value)| (name.clone(), value.clone()))
                .collect()
        })
        .unwrap_or_default();
    Value::Object(kept)
}

/// The player's possession spans, summed: their count and total duration in seconds.
fn player_possession(modules: &Value, id: &Value) -> Value {
    let spans: Vec<f64> = modules["player_possession"]["events"]
        .as_array()
        .map(|events| {
            events
                .iter()
                .filter(|event| event["player_id"] == *id)
                .filter_map(|event| event["duration"].as_f64())
                .collect()
        })
        .unwrap_or_default();
    json!({ "spans": spans.len(), "time": spans.iter().sum::<f64>() })
}

fn oracle(bytes: &[u8]) -> Option<Value> {
    let replay = frames::parse(bytes).ok()?;
    let data = ReplayDataCollector::new().get_replay_data(&replay).ok()?;
    let stats = serde_json::to_value(StatsCollector::new().get_stats(&replay).ok()?).ok()?;
    let modules = &stats["modules"];
    let players = data
        .frame_data
        .players
        .iter()
        .enumerate()
        .map(|(player_idx, (remote_id, _))| {
            let id = serde_json::to_value(remote_id).unwrap_or(Value::Null);
            let team = u8::from(data.meta.team_one.iter().any(|p| p.remote_id == *remote_id));
            let mut row = Map::new();
            row.insert("player_idx".into(), json!(player_idx));
            row.insert("team".into(), json!(team));
            for module in MODULES {
                let found = modules[module]["player_stats"]
                    .as_array()
                    .and_then(|rows| rows.iter().find(|row| row["player_id"] == id))
                    .map(|row| numbers(&row["stats"]))
                    .unwrap_or(Value::Null);
                row.insert(module.into(), found);
            }
            row.insert("player_possession".into(), player_possession(modules, &id));
            Value::Object(row)
        })
        .collect::<Vec<_>>();
    let possession = numbers(&modules["possession"]["stats"]);
    Some(json!({ "players": players, "possession": possession }))
}

fn main() -> ExitCode {
    let Some(path) = std::env::args_os().nth(1) else {
        eprintln!("usage: rl-oracle <replay>");
        return ExitCode::from(2);
    };
    let Ok(bytes) = std::fs::read(path) else {
        eprintln!("cannot read the replay");
        return ExitCode::from(1);
    };
    // subtr-actor can panic on a replay it does not understand: say so, with nothing from the file.
    match catch_unwind(AssertUnwindSafe(|| oracle(&bytes)))
        .ok()
        .flatten()
    {
        Some(value) => {
            println!("{value}");
            ExitCode::SUCCESS
        }
        None => {
            eprintln!("subtr-actor could not read this replay");
            ExitCode::from(1)
        }
    }
}
