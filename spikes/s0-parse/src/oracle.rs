//! T0.8: V1 metrics computed by hand on the frames, next to subtr-actor's aggregate stats.
//! One JSON line per replay; players are anonymous row numbers.

use std::collections::{BTreeMap, HashMap};
use std::path::Path;

use boxcars::ParserBuilder;
use serde_json::{Value, json};
use subtr_actor::{
    BallFrame, BoostPadEventKind, BoostPadSize, GameplayPhase, PlayerFrame, ReplayDataCollector,
    StatsCollector, StatsFrameResolution, StatsTimelineEventCollector,
};

const SUPERSONIC: f32 = 2200.0;
const GROUND_Z: f32 = 20.0;
const HIGH_AIR_Z: f32 = 642.775 + 92.75;
const RAW_USED_PER_SECOND: f64 = 80.0 / 0.93;

#[derive(Default)]
struct Totals(BTreeMap<&'static str, f64>);

impl Totals {
    fn add(&mut self, key: &'static str, value: f64) {
        *self.0.entry(key).or_default() += value;
    }
    fn get(&self, key: &str) -> f64 {
        self.0.get(key).copied().unwrap_or(0.0)
    }
}

fn num(value: &Value, key: &str) -> f64 {
    value.get(key).and_then(Value::as_f64).unwrap_or(0.0)
}

fn ratio(a: f64, b: f64) -> f64 {
    if b > 0.0 { a / b } else { 0.0 }
}

pub fn oracle(path: &Path) {
    let bytes = std::fs::read(path).expect("read");
    let replay = ParserBuilder::new(&bytes).must_parse_network_data().parse().expect("parse");
    let data = ReplayDataCollector::new().get_replay_data(&replay).expect("data");
    let stats = serde_json::to_value(StatsCollector::new().get_stats(&replay).expect("stats")).expect("json");
    let scaffold = StatsTimelineEventCollector::new()
        .with_frame_resolution(StatsFrameResolution::EveryFrame)
        .get_replay_stats_timeline_scaffold(&replay)
        .expect("scaffold");
    let phases: HashMap<u32, (GameplayPhase, f32)> =
        scaffold.frames.iter().map(|f| (f.time.to_bits(), (f.gameplay_phase, f.dt))).collect();

    let fd = &data.frame_data;
    let meta = &fd.metadata_frames;
    let modules = &stats["modules"];
    let map_name = replay.properties.iter().find(|(k, _)| k == "MapName").and_then(|(_, v)| v.as_string()).map(str::to_owned);
    let module_stats = |name: &str, id: &Value| -> Value {
        modules[name]["player_stats"]
            .as_array()
            .and_then(|rows| rows.iter().find(|row| &row["player_id"] == id))
            .map(|row| row["stats"].clone())
            .unwrap_or(Value::Null)
    };

    // Demolition windows: from the demolition to the victim's next respawn.
    let ids: Vec<Value> = fd.players.iter().map(|(id, _)| serde_json::to_value(id).expect("id")).collect();
    let respawns: Vec<(Value, f64, String)> = modules["boost"]["respawn_events"]
        .as_array()
        .map(|events| {
            events
                .iter()
                .map(|e| (e["player_id"].clone(), num(e, "time"), e["kind"].as_str().unwrap_or("?").to_owned()))
                .collect()
        })
        .unwrap_or_default();
    let mut kinds: BTreeMap<String, u32> = BTreeMap::new();
    for (_, _, kind) in &respawns {
        *kinds.entry(kind.clone()).or_default() += 1;
    }
    let mut windows: Vec<Vec<(f32, f32)>> = vec![Vec::new(); ids.len()];
    let mut durations = Vec::new();
    let mut no_respawn = 0;
    let mut frozen = Vec::new();
    for demo in &data.demolish_infos {
        let victim = serde_json::to_value(&demo.victim).expect("id");
        let Some(p) = ids.iter().position(|id| *id == victim) else { continue };
        let next = respawns
            .iter()
            .filter(|(id, time, _)| *id == victim && *time > demo.time as f64)
            .map(|(_, time, _)| *time)
            .fold(f64::INFINITY, f64::min);
        let end = if next.is_finite() && next - (demo.time as f64) < 10.0 {
            durations.push(next - demo.time as f64);
            next as f32
        } else {
            no_respawn += 1;
            demo.time + 3.0
        };
        windows[p].push((demo.time, end));
        // What does the car do while demolished? Distance covered and top speed inside the window.
        let frames = fd.players[p].1.frames();
        let (mut first, mut last, mut top) = (None, None, 0f32);
        for (i, m) in meta.iter().enumerate() {
            if m.time > demo.time + 0.1 && m.time < end - 0.1 {
                if let Some(PlayerFrame::Data { rigid_body, .. }) = frames.get(i) {
                    first.get_or_insert(rigid_body.location);
                    last = Some(rigid_body.location);
                    if let Some(v) = rigid_body.linear_velocity {
                        top = top.max((v.x * v.x + v.y * v.y + v.z * v.z).sqrt());
                    }
                }
            }
        }
        if let (Some(a), Some(b)) = (first, last) {
            let d = ((a.x - b.x).powi(2) + (a.y - b.y).powi(2) + (a.z - b.z).powi(2)).sqrt();
            frozen.push(json!([d, top]));
        }
    }

    // Frame loop.
    let n = meta.len();
    let mut mine: Vec<Totals> = (0..ids.len()).map(|_| Totals::default()).collect();
    let mut max_dt_active = 0f32;
    let mut sum_time_gap = 0f64;
    let mut last_boost: Vec<Option<f32>> = vec![None; ids.len()];
    for i in 0..n {
        let time = meta[i].time;
        let Some(&(phase, dt)) = phases.get(&time.to_bits()) else { continue };
        let live = phase == GameplayPhase::ActivePlay;
        let motion = live || phase == GameplayPhase::KickoffWaitingForTouch;
        if live {
            max_dt_active = max_dt_active.max(dt);
        }
        if i + 1 < n {
            sum_time_gap += ((meta[i + 1].time - time) - dt).abs() as f64;
        }
        let ball = match fd.ball_data.frames().get(i) {
            Some(BallFrame::Data { rigid_body }) => Some(rigid_body.location),
            _ => None,
        };
        // Deepest player of each team, on this frame.
        let mut deepest: [Option<(usize, f32)>; 2] = [None, None];
        let in_window = |p: usize| windows[p].iter().any(|(a, b)| time >= *a && time < *b);
        for (p, (_, player)) in fd.players.iter().enumerate() {
            if let Some(PlayerFrame::Data { rigid_body, is_team_0, .. }) = player.frames().get(i) {
                if in_window(p) {
                    continue;
                }
                let team0 = *is_team_0 != Some(false);
                let rel = if team0 { rigid_body.location.y } else { -rigid_body.location.y };
                let slot = &mut deepest[usize::from(!team0)];
                if slot.is_none_or(|(_, y)| rel < y) {
                    *slot = Some((p, rel));
                }
            }
        }
        for (p, (_, player)) in fd.players.iter().enumerate() {
            let t = &mut mine[p];
            let Some(PlayerFrame::Data { rigid_body, boost_amount, boost_active, is_team_0, .. }) = player.frames().get(i) else {
                if live {
                    t.add("empty_live_s", dt as f64);
                }
                continue;
            };
            let dt = dt as f64;
            let demoed = in_window(p);
            if demoed {
                t.add("demoed_s", dt);
            }
            let previous = last_boost[p].replace(*boost_amount);
            if let Some(prev) = previous {
                if prev > *boost_amount {
                    t.add("all_used_delta", (prev - *boost_amount) as f64);
                }
            }
            if *boost_active {
                t.add("all_used_rate", RAW_USED_PER_SECOND * dt);
            }
            if !motion || demoed {
                continue;
            }
            // Boost and movement: on the motion mask (kickoff approach + live play), like subtr-actor.
            t.add("motion_s", dt);
            let boost = *boost_amount as f64;
            t.add("boost_integral", boost * dt);
            if *boost_amount <= 1.0 {
                t.add("boost_zero_s", dt);
            }
            if *boost_amount >= 254.0 {
                t.add("boost_full_s", dt);
            }
            if let Some(prev) = previous {
                if prev > *boost_amount {
                    t.add("used_delta_raw", (prev - *boost_amount) as f64);
                }
            }
            if *boost_active {
                t.add("used_rate_raw", RAW_USED_PER_SECOND * dt);
            }
            if let Some(v) = rigid_body.linear_velocity {
                let speed = (v.x * v.x + v.y * v.y + v.z * v.z).sqrt();
                t.add("speed_integral", speed as f64 * dt);
                if speed >= SUPERSONIC {
                    t.add("supersonic_s", dt);
                }
            }
            let z = rigid_body.location.z;
            t.add(if z <= GROUND_Z { "ground_s" } else if z >= HIGH_AIR_Z { "high_air_s" } else { "low_air_s" }, dt);

            // Positioning: on live play only, like subtr-actor.
            if !live {
                continue;
            }
            let Some(ball) = ball else { continue };
            let team0 = *is_team_0 != Some(false);
            let sign = if team0 { 1.0 } else { -1.0 };
            let rel = sign * rigid_body.location.y;
            let ball_rel = sign * ball.y;
            t.add("live_s", dt);
            for (cut, def, mid, att) in [
                (5120.0 / 3.0, "def_1707_s", "mid_1707_s", "att_1707_s"),
                (2300.0, "def_2300_s", "mid_2300_s", "att_2300_s"),
            ] {
                t.add(if rel < -cut { def } else if rel > cut { att } else { mid }, dt);
            }
            t.add(if rel > ball_rel { "ahead_s" } else { "behind_s" }, dt);
            if rel > ball_rel + 150.0 {
                t.add("ahead_margin_s", dt);
            } else if rel < ball_rel - 150.0 {
                t.add("behind_margin_s", dt);
            }
            let l = rigid_body.location;
            let d = ((l.x - ball.x).powi(2) + (l.y - ball.y).powi(2) + (l.z - ball.z).powi(2)).sqrt();
            t.add("dist_integral", d as f64 * dt);
            if deepest[usize::from(!team0)].is_some_and(|(q, _)| q == p) {
                t.add("last_back_s", dt);
            }
        }
    }

    // Pads and demolitions from the events.
    let sizes: HashMap<&str, (BoostPadSize, f32)> = data
        .boost_pads
        .iter()
        .filter_map(|pad| pad.pad_id.as_deref().map(|id| (id, (pad.size, pad.position.y))))
        .collect();
    let team_of: Vec<Option<bool>> = fd
        .players
        .iter()
        .map(|(_, player)| {
            player.frames().iter().find_map(|f| match f {
                PlayerFrame::Data { is_team_0, .. } => *is_team_0,
                PlayerFrame::Empty => None,
            })
        })
        .collect();
    for event in &data.boost_pad_events {
        if !matches!(event.kind, BoostPadEventKind::PickedUp { .. }) {
            continue;
        }
        let Some(player) = &event.player else { continue };
        let id = serde_json::to_value(player).expect("id");
        let Some(p) = ids.iter().position(|x| *x == id) else { continue };
        let Some((size, y)) = sizes.get(event.pad_id.as_str()) else { continue };
        mine[p].add(if matches!(size, BoostPadSize::Big) { "pads_big" } else { "pads_small" }, 1.0);
        let sign = if team_of[p] != Some(false) { 1.0 } else { -1.0 };
        if sign * y > 0.0 {
            mine[p].add("pads_enemy_half", 1.0);
        }
    }
    // Variants: raw events may repeat a pickup; subtr-actor's own pickup stream is deduplicated.
    let mut seen = std::collections::HashSet::new();
    for event in &data.boost_pad_events {
        let BoostPadEventKind::PickedUp { sequence } = event.kind else { continue };
        let Some(player) = &event.player else { continue };
        let id = serde_json::to_value(player).expect("id");
        let Some(p) = ids.iter().position(|x| *x == id) else { continue };
        let Some((size, _)) = sizes.get(event.pad_id.as_str()) else { continue };
        let big = matches!(size, BoostPadSize::Big);
        mine[p].add(if big { "raw_big" } else { "raw_small" }, 1.0);
        if seen.insert((event.pad_id.clone(), sequence, p)) {
            mine[p].add(if big { "seq_big" } else { "seq_small" }, 1.0);
            let live = meta
                .get(meta.partition_point(|m| m.time <= event.time).saturating_sub(1))
                .and_then(|m| phases.get(&m.time.to_bits()))
                .is_some_and(|(phase, _)| matches!(phase, GameplayPhase::ActivePlay | GameplayPhase::KickoffWaitingForTouch));
            if live {
                mine[p].add(if big { "seq_big_motion" } else { "seq_small_motion" }, 1.0);
            }
        }
    }
    if let Some(events) = modules["boost"]["pickup_events"].as_array() {
        for event in events {
            let Some(p) = ids.iter().position(|x| *x == event["player_id"]) else { continue };
            let big = event["pad_type"].as_str().is_some_and(|t| t.eq_ignore_ascii_case("big"));
            let active = event["activity"].as_str().is_some_and(|a| a.eq_ignore_ascii_case("active"));
            mine[p].add(if big { "stream_big" } else { "stream_small" }, 1.0);
            if active {
                mine[p].add(if big { "stream_big_active" } else { "stream_small_active" }, 1.0);
            }
        }
    }
    for demo in &data.demolish_infos {
        let attacker = serde_json::to_value(&demo.attacker).expect("id");
        let victim = serde_json::to_value(&demo.victim).expect("id");
        if let Some(p) = ids.iter().position(|x| *x == attacker) {
            mine[p].add("demos_inflicted", 1.0);
        }
        if let Some(p) = ids.iter().position(|x| *x == victim) {
            mine[p].add("demos_taken", 1.0);
        }
    }

    // One row per player: [mine, subtr-actor], same units.
    let mut players = Vec::new();
    for (p, id) in ids.iter().enumerate() {
        let t = &mine[p];
        let b = module_stats("boost", id);
        let m = module_stats("movement", id);
        let o = module_stats("positioning", id);
        let d = module_stats("demo", id);
        let bt = num(&b, "tracked_time");
        let mt = num(&m, "tracked_time");
        let ot = num(&o, "tracked_time");
        let motion = t.get("motion_s");
        let live = t.get("live_s");
        let pct = |a: f64, base: f64| 100.0 * ratio(a, base);
        let mut row = BTreeMap::new();
        row.insert("tracked_boost_s", json!([motion, bt]));
        row.insert("tracked_movement_s", json!([motion, mt]));
        row.insert("tracked_positioning_s", json!([live, ot]));
        row.insert("boost_avg_raw", json!([ratio(t.get("boost_integral"), motion), ratio(num(&b, "boost_integral"), bt)]));
        row.insert("boost_pct_zero", json!([pct(t.get("boost_zero_s"), motion), pct(num(&b, "time_zero_boost"), bt)]));
        row.insert("boost_pct_full", json!([pct(t.get("boost_full_s"), motion), pct(num(&b, "time_hundred_boost"), bt)]));
        row.insert("used_per_min_delta", json!([60.0 * ratio(t.get("used_delta_raw"), motion), 60.0 * ratio(num(&b, "amount_used"), bt)]));
        row.insert("used_per_min_rate", json!([60.0 * ratio(t.get("used_rate_raw"), motion), 60.0 * ratio(num(&b, "amount_used"), bt)]));
        row.insert("pads_big", json!([t.get("pads_big"), num(&b, "big_pads_collected")]));
        row.insert("pads_small", json!([t.get("pads_small"), num(&b, "small_pads_collected")]));
        let (tb, ts) = (num(&b, "big_pads_collected"), num(&b, "small_pads_collected"));
        let (ib, is) = (num(&b, "big_pads_collected_inactive"), num(&b, "small_pads_collected_inactive"));
        row.insert("pads_big_raw_vs_collected", json!([t.get("raw_big"), tb]));
        row.insert("pads_big_seq_vs_collected", json!([t.get("seq_big"), tb]));
        row.insert("pads_big_seq_motion_vs_collected", json!([t.get("seq_big_motion"), tb]));
        row.insert("pads_small_seq_vs_collected", json!([t.get("seq_small"), ts]));
        row.insert("pads_small_seq_motion_vs_collected", json!([t.get("seq_small_motion"), ts]));
        row.insert("pads_big_stream_vs_collected", json!([t.get("stream_big"), tb]));
        row.insert("pads_small_stream_vs_collected", json!([t.get("stream_small"), ts]));
        row.insert("pads_big_stream_active_vs_collected", json!([t.get("stream_big_active"), tb]));
        row.insert("pads_small_stream_active_vs_collected", json!([t.get("stream_small_active"), ts]));
        row.insert("pads_big_seq_vs_collected_plus_inactive", json!([t.get("seq_big"), tb + ib]));
        row.insert("pads_small_seq_vs_collected_plus_inactive", json!([t.get("seq_small"), ts + is]));
        row.insert("used_all_frames_delta", json!([60.0 * ratio(t.get("all_used_delta"), motion), 60.0 * ratio(num(&b, "amount_used"), bt)]));
        row.insert("used_all_frames_rate", json!([60.0 * ratio(t.get("all_used_rate"), motion), 60.0 * ratio(num(&b, "amount_used"), bt)]));
        row.insert("speed_avg", json!([ratio(t.get("speed_integral"), motion), ratio(num(&m, "speed_integral"), mt)]));
        row.insert("pct_supersonic", json!([pct(t.get("supersonic_s"), motion), pct(num(&m, "time_supersonic_speed"), mt)]));
        row.insert("pct_ground", json!([pct(t.get("ground_s"), motion), pct(num(&m, "time_on_ground"), mt)]));
        row.insert("pct_low_air", json!([pct(t.get("low_air_s"), motion), pct(num(&m, "time_low_air"), mt)]));
        row.insert("pct_high_air", json!([pct(t.get("high_air_s"), motion), pct(num(&m, "time_high_air"), mt)]));
        row.insert("third_def_1707", json!([pct(t.get("def_1707_s"), live), pct(num(&o, "time_defensive_third"), ot)]));
        row.insert("third_mid_1707", json!([pct(t.get("mid_1707_s"), live), pct(num(&o, "time_neutral_third"), ot)]));
        row.insert("third_att_1707", json!([pct(t.get("att_1707_s"), live), pct(num(&o, "time_offensive_third"), ot)]));
        row.insert("third_def_2300", json!([pct(t.get("def_2300_s"), live), pct(num(&o, "time_defensive_third"), ot)]));
        row.insert("third_mid_2300", json!([pct(t.get("mid_2300_s"), live), pct(num(&o, "time_neutral_third"), ot)]));
        row.insert("third_att_2300", json!([pct(t.get("att_2300_s"), live), pct(num(&o, "time_offensive_third"), ot)]));
        row.insert("ahead_no_margin", json!([pct(t.get("ahead_s"), live), pct(num(&o, "time_in_front_of_ball"), ot)]));
        row.insert("behind_no_margin", json!([pct(t.get("behind_s"), live), pct(num(&o, "time_behind_ball"), ot)]));
        row.insert("ahead_margin_150", json!([pct(t.get("ahead_margin_s"), live), pct(num(&o, "time_in_front_of_ball"), ot)]));
        row.insert("behind_margin_150", json!([pct(t.get("behind_margin_s"), live), pct(num(&o, "time_behind_ball"), ot)]));
        row.insert("dist_ball_avg", json!([ratio(t.get("dist_integral"), live), ratio(num(&o, "sum_distance_to_ball"), ot)]));
        row.insert("pct_last_back", json!([pct(t.get("last_back_s"), live), pct(num(&o, "time_most_back"), ot)]));
        row.insert("demos_inflicted", json!([t.get("demos_inflicted"), num(&d, "demos_inflicted")]));
        row.insert("demos_taken", json!([t.get("demos_taken"), num(&d, "demos_taken")]));
        row.insert("demoed_s", json!([t.get("demoed_s"), num(&o, "time_demolished")]));
        row.insert("empty_live_s", json!([t.get("empty_live_s"), 0.0]));
        players.push(json!(row));
    }
    let boost_pickup_kinds: BTreeMap<String, u32> = modules["boost"]["pickup_events"].as_array().map(|events| {
        let mut out = BTreeMap::new();
        for e in events {
            *out.entry(e["detection"].as_str().unwrap_or("?").to_owned()).or_default() += 1;
        }
        out
    }).unwrap_or_default();
    println!("{}", json!({
        "map": map_name,
        "team_size": data.meta.team_zero.len().max(data.meta.team_one.len()),
        "players": players,
        "respawn_kinds": kinds,
        "demo_respawn_s": durations,
        "demo_without_respawn": no_respawn,
        "demo_car": frozen,
        "max_dt_active": max_dt_active,
        "dt_vs_time_gap_total": sum_time_gap,
        "pickup_detection": boost_pickup_kinds,
    }));
}
