//! `events.json`: who played, and what happened at an exact time.

use std::collections::{HashMap, HashSet};

use boxcars::{RemoteId, Replay};
use serde::Serialize;
use subtr_actor::{BoostPadEventKind, BoostPadSize, PlayerStatEventKind, ResolvedBoostPad};

use crate::detections::{self, BeatenToBall, FiftyFifty, Kickoff, Touch};
use crate::frames::{Collected, phase_code};
use crate::header::PARSER_VERSION;
use crate::identity;

/// Version 2 adds subtr-actor's detections (`docs/PLAN-V2.md`, T11.1). The header and the frames
/// keep version 1.
pub const EVENTS_SCHEMA_VERSION: u32 = 2;

#[derive(Debug, Serialize)]
pub struct Events {
    pub schema_version: u32,
    pub parser_version: &'static str,
    /// The `--fps` cap, when there is one.
    pub fps: Option<f32>,
    pub playlist_id: Option<i32>,
    pub duration_s: f32,
    /// A car left the standard arena in live play: the metrics should not be trusted.
    pub arena_out_of_bounds: bool,
    pub roster: Vec<RosterPlayer>,
    pub goals: Vec<Goal>,
    pub demolitions: Vec<Demolition>,
    pub pad_pickups: Vec<PadPickup>,
    /// Pickups of a pad the layout does not resolve. Under 0.5 % on real replays.
    pub unresolved_pad_pickups: u32,
    pub stat_events: Vec<StatEvent>,
    /// subtr-actor's detections; all four are null when its detectors failed on this replay.
    pub touches: Option<Vec<Touch>>,
    pub kickoffs: Option<Vec<Kickoff>>,
    pub fifty_fifties: Option<Vec<FiftyFifty>>,
    pub beaten_to_ball: Option<Vec<BeatenToBall>>,
}

#[derive(Debug, Serialize)]
pub struct RosterPlayer {
    pub player_idx: usize,
    pub platform: &'static str,
    pub platform_id: Option<String>,
    /// `AnonymizedName` for a player who asked for anonymity: the replay still holds their real
    /// name, which must not be shown to others.
    pub name: String,
    pub team: u8,
    pub anonymized: bool,
}

#[derive(Debug, Serialize)]
pub struct Goal {
    pub frame: usize,
    pub time_s: f32,
    pub team: u8,
    pub player_idx: Option<usize>,
    pub score_blue: Option<i32>,
    pub score_orange: Option<i32>,
}

#[derive(Debug, Serialize)]
pub struct Demolition {
    pub frame: usize,
    pub time_s: f32,
    pub attacker_idx: Option<usize>,
    pub victim_idx: Option<usize>,
    pub x: f32,
    pub y: f32,
    pub z: f32,
}

#[derive(Debug, Serialize)]
pub struct PadPickup {
    pub frame: usize,
    pub time_s: f32,
    pub phase: u8,
    pub player_idx: usize,
    pub pad_index: usize,
    pub size: &'static str,
    pub x: f32,
    pub y: f32,
    pub z: f32,
}

#[derive(Debug, Serialize)]
pub struct StatEvent {
    pub frame: usize,
    pub time_s: f32,
    pub player_idx: usize,
    pub kind: &'static str,
}

fn index_of(ids: &[&RemoteId], id: &RemoteId) -> Option<usize> {
    ids.iter().position(|candidate| *candidate == id)
}

/// Respawn times of the pads: nobody can take a pad again sooner.
const BIG_PAD_RESPAWN_S: f32 = 10.0;
const SMALL_PAD_RESPAWN_S: f32 = 4.0;

/// Tells real pickups from replicated repeats. The raw events repeat a pickup (27 big pads
/// against 18 at the median on real replays), but a pad's sequence number is not unique: it comes
/// back after a real respawn, and old replays always say 1. So a repeat is only what the pad's
/// respawn time makes impossible.
#[derive(Default)]
struct PadTracker {
    sequence_times: HashMap<(String, u8), f32>,
    pickup_times: HashMap<String, f32>,
    unavailable: HashSet<String>,
}

impl PadTracker {
    fn available(&mut self, pad: &str) {
        self.unavailable.remove(pad);
    }

    /// True for a real pickup, false for a repeat.
    fn pick_up(&mut self, pad: &str, sequence: u8, time: f32, respawn: f32) -> bool {
        let too_soon = |last: Option<&f32>| last.is_some_and(|last| time - last < respawn);
        let repeated = too_soon(self.sequence_times.get(&(pad.to_owned(), sequence)));
        let not_back = self.unavailable.contains(pad) && too_soon(self.pickup_times.get(pad));
        if repeated || not_back {
            return false;
        }
        self.sequence_times.insert((pad.to_owned(), sequence), time);
        self.pickup_times.insert(pad.to_owned(), time);
        self.unavailable.insert(pad.to_owned());
        true
    }
}

fn pad_pickups(collected: &Collected, ids: &[&RemoteId]) -> (Vec<PadPickup>, u32) {
    let data = &collected.data;
    let pads: HashMap<&str, &ResolvedBoostPad> = data
        .boost_pads
        .iter()
        .filter_map(|pad| pad.pad_id.as_deref().map(|id| (id, pad)))
        .collect();
    let times = collected.times();
    let mut tracker = PadTracker::default();
    let mut pickups = Vec::new();
    let mut unresolved = 0;
    for event in &data.boost_pad_events {
        let BoostPadEventKind::PickedUp { sequence } = event.kind else {
            tracker.available(&event.pad_id);
            continue;
        };
        let pad = pads.get(event.pad_id.as_str()).copied();
        let respawn = match pad.map(|pad| pad.size) {
            Some(BoostPadSize::Big) => BIG_PAD_RESPAWN_S,
            _ => SMALL_PAD_RESPAWN_S,
        };
        if !tracker.pick_up(&event.pad_id, sequence, event.time, respawn) {
            continue;
        }
        let Some(player_idx) = event
            .player
            .as_ref()
            .and_then(|player| index_of(ids, player))
        else {
            continue;
        };
        let Some(pad) = pad else {
            unresolved += 1;
            continue;
        };
        let at = times
            .partition_point(|time| *time <= event.time)
            .saturating_sub(1);
        pickups.push(PadPickup {
            frame: event.frame,
            time_s: event.time,
            phase: collected.phases.get(at).copied().map_or(0, phase_code),
            player_idx,
            pad_index: pad.index,
            size: match pad.size {
                BoostPadSize::Big => "big",
                BoostPadSize::Small => "small",
            },
            x: pad.position.x,
            y: pad.position.y,
            z: pad.position.z,
        });
    }
    (pickups, unresolved)
}

pub fn extract(replay: &Replay, collected: &Collected, fps: Option<f32>) -> Events {
    let data = &collected.data;
    let frame_data = &data.frame_data;
    let ids: Vec<&RemoteId> = frame_data.players.iter().map(|(id, _)| id).collect();
    let anonymity = identity::anonymity_by_player(replay);

    let roster = ids
        .iter()
        .enumerate()
        .map(|(player_idx, id)| {
            let (platform, platform_id) = identity::from_remote_id(id);
            let info = data
                .meta
                .player_order()
                .find(|player| player.remote_id == **id);
            let wish = anonymity.get(*id);
            let anonymized = wish.is_some_and(|wish| wish.requested);
            let name = if anonymized {
                wish.and_then(|wish| wish.anonymized_name.clone())
                    .unwrap_or_else(|| identity::ANONYMOUS_NAME.to_owned())
            } else {
                info.map(|player| player.name.clone()).unwrap_or_default()
            };
            RosterPlayer {
                player_idx,
                platform,
                platform_id,
                name,
                team: collected.team[player_idx],
                anonymized,
            }
        })
        .collect();

    let goals = data
        .goal_events
        .iter()
        .map(|goal| Goal {
            frame: goal.frame,
            time_s: goal.time,
            team: u8::from(!goal.scoring_team_is_team_0),
            player_idx: goal
                .player
                .as_ref()
                .and_then(|player| index_of(&ids, player)),
            score_blue: goal.team_zero_score,
            score_orange: goal.team_one_score,
        })
        .collect();

    let demolitions = data
        .demolish_infos
        .iter()
        .map(|demolition| Demolition {
            frame: demolition.frame,
            time_s: demolition.time,
            attacker_idx: index_of(&ids, &demolition.attacker),
            victim_idx: index_of(&ids, &demolition.victim),
            x: demolition.victim_location.x,
            y: demolition.victim_location.y,
            z: demolition.victim_location.z,
        })
        .collect();

    let stat_events = data
        .player_stat_events
        .iter()
        .filter_map(|event| {
            Some(StatEvent {
                frame: event.frame,
                time_s: event.time,
                player_idx: index_of(&ids, &event.player)?,
                kind: match event.kind {
                    PlayerStatEventKind::Shot => "shot",
                    PlayerStatEventKind::Save => "save",
                    PlayerStatEventKind::Assist => "assist",
                },
            })
        })
        .collect();

    let (pad_pickups, unresolved_pad_pickups) = pad_pickups(collected, &ids);
    let detected = detections::detect(replay, &ids);
    let (touches, kickoffs, fifty_fifties, beaten_to_ball) = match detected {
        Some(found) => (
            Some(found.touches),
            Some(found.kickoffs),
            Some(found.fifty_fifties),
            Some(found.beaten_to_ball),
        ),
        None => (None, None, None, None),
    };
    Events {
        schema_version: EVENTS_SCHEMA_VERSION,
        parser_version: PARSER_VERSION,
        fps,
        playlist_id: data.meta.game_type.playlist_id,
        duration_s: frame_data.duration(),
        arena_out_of_bounds: collected.arena_out_of_bounds(),
        roster,
        goals,
        demolitions,
        pad_pickups,
        unresolved_pad_pickups,
        stat_events,
        touches,
        kickoffs,
        fifty_fifties,
        beaten_to_ball,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_repeat_inside_the_respawn_time_is_dropped() {
        let mut tracker = PadTracker::default();
        assert!(tracker.pick_up("pad", 7, 100.0, BIG_PAD_RESPAWN_S));
        assert!(!tracker.pick_up("pad", 7, 100.5, BIG_PAD_RESPAWN_S));
        assert!(!tracker.pick_up("pad", 7, 109.9, BIG_PAD_RESPAWN_S));
    }

    #[test]
    fn the_same_sequence_after_a_respawn_is_a_real_pickup() {
        let mut tracker = PadTracker::default();
        assert!(tracker.pick_up("pad", 1, 100.0, SMALL_PAD_RESPAWN_S));
        assert!(tracker.pick_up("pad", 1, 104.0, SMALL_PAD_RESPAWN_S));
        assert!(tracker.pick_up("pad", 1, 200.0, SMALL_PAD_RESPAWN_S));
    }

    #[test]
    fn a_pad_not_yet_back_cannot_be_taken_under_another_sequence() {
        let mut tracker = PadTracker::default();
        assert!(tracker.pick_up("pad", 1, 100.0, BIG_PAD_RESPAWN_S));
        assert!(!tracker.pick_up("pad", 2, 105.0, BIG_PAD_RESPAWN_S));
    }

    #[test]
    fn an_available_event_clears_the_pad() {
        let mut tracker = PadTracker::default();
        assert!(tracker.pick_up("pad", 1, 100.0, BIG_PAD_RESPAWN_S));
        tracker.available("pad");
        assert!(tracker.pick_up("pad", 2, 105.0, BIG_PAD_RESPAWN_S));
    }

    #[test]
    fn pads_do_not_interfere() {
        let mut tracker = PadTracker::default();
        assert!(tracker.pick_up("a", 1, 100.0, BIG_PAD_RESPAWN_S));
        assert!(tracker.pick_up("b", 1, 100.0, BIG_PAD_RESPAWN_S));
    }
}
