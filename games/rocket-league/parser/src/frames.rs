//! Collects the replay's frames and game phases, and applies what the V1 analysis relies on.
//!
//! This deliberately avoids `StatsCollector` and the stats timeline: on a long replay they take
//! minutes and hundreds of megabytes (`spikes/s0-parse/RAPPORT.md`).

use std::collections::HashMap;
use std::panic::{AssertUnwindSafe, catch_unwind};

use boxcars::{ParserBuilder, Replay};
use subtr_actor::{
    Collector, FrameEventsState, GameplayPhase, GameplayState, LivePlayTracker, PlayerFrame,
    ProcessorView, ReplayData, ReplayDataCollector, ReplayProcessor, SubtrActorResult, TimeAdvance,
};

use crate::error::Failure;
use crate::header::looks_like_replay;

/// Respawn after a demolition: 3.20 s at the 5th percentile, 3.21 s at the median.
pub const DEMOLISHED_SECONDS: f32 = 3.2;

/// Playlists observed on the standard arena. A replay without a playlist (old ones) goes through.
const STANDARD_PLAYLISTS: [i32; 9] = [1, 2, 3, 6, 8, 10, 11, 13, 34];

/// Maps with other dimensions, which a private match can use under a standard playlist.
const NON_STANDARD_MAPS: [&str; 3] = ["ShatterShot_P", "HoopsStadium_P", "HoopsStreet_P"];

/// A car beyond these, in live play and not demolished, is not on the standard arena. Measured:
/// `|x|` up to 4094, `|y|` up to 5991 in the goals.
const ARENA_LIMIT_X: f32 = 4200.0;
const ARENA_LIMIT_Y: f32 = 6100.0;

#[derive(Default)]
struct PhaseCollector {
    tracker: LivePlayTracker,
    phases: HashMap<u32, GameplayPhase>,
}

impl Collector for PhaseCollector {
    fn process_frame(
        &mut self,
        processor: &dyn ProcessorView,
        _frame: &boxcars::Frame,
        _frame_number: usize,
        current_time: f32,
    ) -> SubtrActorResult<TimeAdvance> {
        let scores = processor.get_team_scores().ok();
        let gameplay = GameplayState {
            game_state: processor.get_game_state(),
            ball_has_been_hit: processor.get_ball_has_been_hit().ok(),
            kickoff_countdown_time: processor.get_replicated_game_state_time_remaining().ok(),
            team_zero_score: scores.map(|score| score.0),
            team_one_score: scores.map(|score| score.1),
            ..Default::default()
        };
        let events = FrameEventsState {
            goal_events: processor.current_frame_goal_events().to_vec(),
            ..Default::default()
        };
        let state = self.tracker.state_parts(&gameplay, &events);
        self.phases
            .insert(current_time.to_bits(), state.gameplay_phase);
        Ok(TimeAdvance::NextFrame)
    }
}

/// A frame's phase, as stored in `frames.parquet`.
pub const fn phase_code(phase: GameplayPhase) -> u8 {
    match phase {
        GameplayPhase::KickoffCountdown => 1,
        GameplayPhase::KickoffWaitingForTouch => 2,
        GameplayPhase::ActivePlay => 3,
        GameplayPhase::PostGoal => 4,
        GameplayPhase::Unknown => 0,
    }
}

/// Everything the outputs are built from.
pub struct Collected {
    pub data: ReplayData,
    /// The replay's frames to write, as indices. All of them unless `--fps` caps the rate.
    pub kept: Vec<usize>,
    /// Phase of every frame of the replay.
    pub phases: Vec<GameplayPhase>,
    /// Per player then per frame, in the order of `data.frame_data.players`.
    pub demolished: Vec<Vec<bool>>,
    pub team: Vec<u8>,
}

/// Decodes the network stream. Its failure leaves the header usable: `header_only`.
pub fn parse(bytes: &[u8]) -> Result<Replay, Failure> {
    if !looks_like_replay(bytes) {
        return Err(Failure::NotAReplay);
    }
    ParserBuilder::new(bytes)
        .must_parse_network_data()
        .always_check_crc()
        .parse()
        .map_err(|error| Failure::from_parse_error(&error))
}

/// Keeps a frame when at least `1 / fps` passed since the last kept one.
fn select_frames(times: &[f32], fps: Option<f32>) -> Vec<usize> {
    let Some(step) = fps.filter(|fps| *fps > 0.0).map(|fps| 1.0 / fps) else {
        return (0..times.len()).collect();
    };
    let mut kept = Vec::new();
    let mut next = f32::NEG_INFINITY;
    for (index, time) in times.iter().enumerate() {
        if *time >= next {
            kept.push(index);
            next = *time + step * 0.999;
        }
    }
    kept
}

fn is_live(phase: GameplayPhase) -> bool {
    matches!(
        phase,
        GameplayPhase::ActivePlay | GameplayPhase::KickoffWaitingForTouch
    )
}

/// Marks the frames after a demolition, until the respawn or the end of the live phase. The car
/// stays "present" meanwhile, with a position that is wrong. A touch during the kickoff is not a
/// change of phase here: the demolished player is still waiting to respawn.
pub fn demolished_window(
    times: &[f32],
    phases: &[GameplayPhase],
    demolition_time: f32,
    frames: &mut [bool],
) {
    let start = times.partition_point(|time| *time < demolition_time);
    let Some(first) = phases.get(start).copied() else {
        return;
    };
    let end_time = demolition_time + DEMOLISHED_SECONDS;
    for index in start..times.len() {
        let same_phase = phases[index] == first || (is_live(phases[index]) && is_live(first));
        if times[index] >= end_time || !same_phase {
            break;
        }
        frames[index] = true;
    }
}

/// Dropshot, Hoops and other modes do not fit the V1 constants.
fn is_supported(playlist: Option<i32>, map: Option<&str>) -> bool {
    let standard_map = map.is_none_or(|map| !NON_STANDARD_MAPS.contains(&map));
    let standard_playlist = playlist.is_none_or(|id| STANDARD_PLAYLISTS.contains(&id));
    standard_map && standard_playlist
}

/// Runs subtr-actor on the decoded replay. A panic in there is that replay's failure, not ours.
pub fn collect(replay: &Replay, fps: Option<f32>) -> Result<Collected, Failure> {
    let run = || -> Option<(ReplayData, PhaseCollector)> {
        let mut phases = PhaseCollector::default();
        let mut data = ReplayDataCollector::new();
        let mut processor = ReplayProcessor::new(replay).ok()?;
        processor.process_all(&mut [&mut data, &mut phases]).ok()?;
        Some((data.into_replay_data(processor).ok()?, phases))
    };
    let (data, phase_collector) = catch_unwind(AssertUnwindSafe(run))
        .ok()
        .flatten()
        .ok_or(Failure::ProcessorFailed)?;

    let map = replay
        .properties
        .iter()
        .find(|(key, _)| key == "MapName")
        .and_then(|(_, value)| value.as_string());
    if !is_supported(data.meta.game_type.playlist_id, map) {
        return Err(Failure::UnsupportedMode);
    }

    let times: Vec<f32> = data
        .frame_data
        .metadata_frames
        .iter()
        .map(|frame| frame.time)
        .collect();
    let phases: Vec<GameplayPhase> = times
        .iter()
        .map(|time| {
            phase_collector
                .phases
                .get(&time.to_bits())
                .copied()
                .unwrap_or_default()
        })
        .collect();

    let players = &data.frame_data.players;
    let mut demolished = vec![vec![false; times.len()]; players.len()];
    for demolition in &data.demolish_infos {
        if let Some(index) = players.iter().position(|(id, _)| *id == demolition.victim) {
            demolished_window(&times, &phases, demolition.time, &mut demolished[index]);
        }
    }
    let team = players
        .iter()
        .map(|(id, _)| {
            u8::from(
                data.meta
                    .team_one
                    .iter()
                    .any(|player| player.remote_id == *id),
            )
        })
        .collect();
    let kept = select_frames(&times, fps);
    Ok(Collected {
        data,
        kept,
        phases,
        demolished,
        team,
    })
}

impl Collected {
    pub fn times(&self) -> Vec<f32> {
        self.data
            .frame_data
            .metadata_frames
            .iter()
            .map(|frame| frame.time)
            .collect()
    }

    /// True when a car left the standard arena in live play: the metrics cannot be trusted.
    pub fn arena_out_of_bounds(&self) -> bool {
        self.data
            .frame_data
            .players
            .iter()
            .enumerate()
            .any(|(player, (_, data))| {
                data.frames().iter().enumerate().any(|(index, frame)| {
                    let PlayerFrame::Data { rigid_body, .. } = frame else {
                        return false;
                    };
                    self.phases.get(index) == Some(&GameplayPhase::ActivePlay)
                        && !self.demolished[player][index]
                        && (rigid_body.location.x.abs() > ARENA_LIMIT_X
                            || rigid_body.location.y.abs() > ARENA_LIMIT_Y)
                })
            })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use GameplayPhase::{ActivePlay, KickoffCountdown, KickoffWaitingForTouch, PostGoal};

    #[test]
    fn frames_are_all_kept_without_a_cap() {
        assert_eq!(select_frames(&[0.0, 0.01, 0.02], None), vec![0, 1, 2]);
        assert_eq!(select_frames(&[0.0, 0.01, 0.02], Some(0.0)), vec![0, 1, 2]);
    }

    #[test]
    fn a_cap_drops_frames_that_come_too_soon() {
        let times: Vec<f32> = (0..10).map(|index| index as f32 * 0.05).collect();
        assert_eq!(select_frames(&times, Some(10.0)), vec![0, 2, 4, 6, 8]);
    }

    fn window(phases: &[GameplayPhase], at: f32) -> Vec<bool> {
        let times: Vec<f32> = (0..phases.len()).map(|index| index as f32).collect();
        let mut frames = vec![false; phases.len()];
        demolished_window(&times, phases, at, &mut frames);
        frames
    }

    #[test]
    fn a_demolition_lasts_until_the_respawn() {
        let frames = window(&[ActivePlay; 8], 1.0);
        assert_eq!(frames, [false, true, true, true, true, false, false, false]);
    }

    #[test]
    fn a_goal_ends_the_window() {
        let phases = [
            ActivePlay, ActivePlay, PostGoal, PostGoal, PostGoal, PostGoal,
        ];
        assert_eq!(
            window(&phases, 0.0),
            [true, true, false, false, false, false]
        );
    }

    #[test]
    fn a_touch_during_the_kickoff_does_not_end_it() {
        let phases = [
            KickoffWaitingForTouch,
            KickoffWaitingForTouch,
            ActivePlay,
            ActivePlay,
        ];
        assert_eq!(window(&phases, 0.0), [true, true, true, true]);
    }

    #[test]
    fn a_new_kickoff_ends_it() {
        let phases = [ActivePlay, KickoffCountdown, KickoffCountdown];
        assert_eq!(window(&phases, 0.0), [true, false, false]);
    }

    #[test]
    fn a_demolition_after_the_last_frame_marks_nothing() {
        assert_eq!(window(&[ActivePlay; 2], 5.0), [false, false]);
    }

    #[test]
    fn supported_modes() {
        assert!(is_supported(Some(11), Some("cs_p")));
        assert!(is_supported(None, Some("cs_p")));
        assert!(is_supported(None, None));
        assert!(!is_supported(Some(29), Some("cs_p")));
        assert!(!is_supported(Some(6), Some("ShatterShot_P")));
    }
}
