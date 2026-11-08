//! Spike of step 10: runs a chosen set of subtr-actor analysis nodes on one replay, without
//! `StatsCollector` or the timeline, and writes what they found. Throwaway code.
//!
//! Usage:
//!   s10-probe list
//!   s10-probe run <replay> <out.json> <node,node,...>
//!
//! Privacy: every player id in the output is replaced by the player's row in `rl-parse`'s
//! roster (`{"idx": n}`); nothing else names a player.

use std::process::ExitCode;
use std::time::Instant;

use rl_parse::frames;
use serde_json::{Value, json};
use subtr_actor::ReplayDataCollector;
use subtr_actor::analysis_graph::{
    builtin_analysis_node_names, collect_builtin_analysis_graph_for_replay,
};

/// Replaces every value equal to a known player id by its roster row, recursively.
fn anonymize(value: &mut Value, ids: &[(Value, usize)]) {
    if let Some((_, idx)) = ids.iter().find(|(id, _)| id == value) {
        *value = json!({ "idx": idx });
        return;
    }
    match value {
        Value::Array(items) => items.iter_mut().for_each(|item| anonymize(item, ids)),
        Value::Object(fields) => fields.values_mut().for_each(|item| anonymize(item, ids)),
        _ => {}
    }
}

fn events<T: serde::Serialize>(items: &[T]) -> Value {
    serde_json::to_value(items).unwrap_or(Value::Null)
}

fn run(path: &str, out: &str, nodes: &str) -> Result<(), String> {
    let bytes = std::fs::read(path).map_err(|e| e.to_string())?;
    let replay = frames::parse(&bytes).map_err(|_| "parse".to_string())?;

    let data = ReplayDataCollector::new()
        .get_replay_data(&replay)
        .map_err(|_| "replay data".to_string())?;
    let ids: Vec<(Value, usize)> = data
        .frame_data
        .players
        .iter()
        .enumerate()
        .map(|(idx, (id, _))| (serde_json::to_value(id).unwrap_or(Value::Null), idx))
        .collect();

    let names: Vec<&str> = nodes.split(',').filter(|n| !n.is_empty()).collect();
    let started = Instant::now();
    let mut graph = collect_builtin_analysis_graph_for_replay(&replay, names.iter().copied())
        .map_err(|_| "graph".to_string())?;
    graph.finish().map_err(|_| "finish".to_string())?;
    let elapsed_ms = started.elapsed().as_millis();

    let mut found = serde_json::Map::new();
    if let Some(state) = graph.state::<subtr_actor::TouchCalculator>() {
        found.insert("touches".into(), events(state.events()));
    }
    if let Some(state) = graph.state::<subtr_actor::PossessionCalculator>() {
        found.insert("possession".into(), events(state.events()));
    }
    if let Some(state) = graph.state::<subtr_actor::RotationCalculator>() {
        found.insert("rotation_roles".into(), events(&state.role_events()));
    }
    if let Some(state) = graph.state::<subtr_actor::KickoffCalculator>() {
        found.insert("kickoffs".into(), events(state.events()));
    }
    if let Some(state) = graph.state::<subtr_actor::FiftyFiftyCalculator>() {
        found.insert("fifty_fifty".into(), events(state.events()));
    }
    if let Some(state) = graph.state::<subtr_actor::BeatenToBallCalculator>() {
        found.insert("beaten_to_ball".into(), events(state.events()));
    }
    if let Some(state) = graph.state::<subtr_actor::RushCalculator>() {
        found.insert("rush".into(), events(state.events()));
    }

    let mut document = json!({
        "elapsed_ms": elapsed_ms,
        "nodes": names,
        "players": ids.len(),
        "found": Value::Object(found),
    });
    anonymize(&mut document, &ids);
    std::fs::write(out, serde_json::to_vec(&document).map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().collect();
    match args.get(1).map(String::as_str) {
        Some("list") => {
            for name in builtin_analysis_node_names() {
                println!("{name}");
            }
            ExitCode::SUCCESS
        }
        Some("run") if args.len() == 5 => match run(&args[2], &args[3], &args[4]) {
            Ok(()) => ExitCode::SUCCESS,
            Err(code) => {
                eprintln!("failed: {code}");
                ExitCode::FAILURE
            }
        },
        _ => {
            eprintln!("usage: s10-probe list | run <replay> <out.json> <nodes>");
            ExitCode::from(2)
        }
    }
}
