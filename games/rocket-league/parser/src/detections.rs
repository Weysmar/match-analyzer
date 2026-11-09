//! What subtr-actor's detectors find in a replay (DV1 and DV7 of `docs/PLAN-V2.md`): touches,
//! kickoffs, 50/50s and players beaten to the ball. They need details the frames do not keep (the
//! replicated `HitTeamNum` marker, dodge bytes, kickoff phases), so they run here, on the replay.
//!
//! Only the analysis graph's needed nodes run, never `StatsCollector` or the timeline (section 6 of
//! CLAUDE.md). Measured at step 10: 0.7 s at the median, 3 s at most on the corpus.
//!
//! A failure of the detectors must not cost the match its frames: everything is then `None`, and
//! the analysis reads it as "not detected".

use std::panic::{AssertUnwindSafe, catch_unwind};

use boxcars::{RemoteId, Replay};
use serde::Serialize;
use subtr_actor::analysis_graph::collect_builtin_analysis_graph_for_replay;
use subtr_actor::{
    BeatenToBallCalculator, BeatenToBallEvent, FiftyFiftyCalculator, FiftyFiftyEvent,
    KickoffCalculator, KickoffEvent, KickoffOutcome, KickoffTakerEvent, TouchCalculator,
    TouchClassificationEvent,
};

/// The graph pulls in the nodes these depend on.
const NODES: [&str; 4] = ["touch", "kickoff", "fifty_fifty", "beaten_to_ball"];

#[derive(Debug, Serialize)]
pub struct Touch {
    pub frame: usize,
    pub time_s: f32,
    pub player_idx: usize,
    pub team: u8,
    /// Change of the ball's speed the touch caused, in uu/s.
    pub ball_speed_change: f32,
    /// subtr-actor's classification, as it names it: `kind` (strength), `height_band`, `surface`.
    pub kind: Option<String>,
    pub height_band: Option<String>,
    pub surface: Option<String>,
    /// Both teams touched within a frame or so.
    pub contested: bool,
}

#[derive(Debug, Serialize)]
pub struct KickoffTaker {
    pub player_idx: usize,
    pub team: u8,
    /// From the end of the countdown to the taker's touch.
    pub time_to_ball_s: Option<f32>,
    pub start_boost: Option<f32>,
    pub boost_used: f32,
}

#[derive(Debug, Serialize)]
pub struct Kickoff {
    pub start_frame: usize,
    pub start_time_s: f32,
    pub end_frame: usize,
    pub end_time_s: f32,
    /// `center`, `center_offset`, `diagonal` or `unknown`.
    pub kickoff_type: String,
    pub first_touch_frame: Option<usize>,
    pub first_touch_time_s: Option<f32>,
    pub first_touch_player_idx: Option<usize>,
    /// The winning team, `None` when neutral or unknown.
    pub winner_team: Option<u8>,
    /// `win`, `neutral` or `unknown`.
    pub outcome: &'static str,
    pub goal: bool,
    pub time_to_goal_s: Option<f32>,
    pub takers: Vec<KickoffTaker>,
}

#[derive(Debug, Serialize)]
pub struct FiftyFifty {
    pub start_frame: usize,
    pub start_time_s: f32,
    pub resolve_frame: usize,
    pub resolve_time_s: f32,
    pub is_kickoff: bool,
    pub blue_player_idx: Option<usize>,
    pub orange_player_idx: Option<usize>,
    pub winner_team: Option<u8>,
    /// The team with the ball once the contest resolved.
    pub possession_team: Option<u8>,
}

#[derive(Debug, Serialize)]
pub struct BeatenToBall {
    pub frame: usize,
    pub time_s: f32,
    /// The player who was committed to the ball and got beaten.
    pub player_idx: usize,
    pub winner_idx: Option<usize>,
    pub team: u8,
    pub distance_at_touch: f32,
    pub margin_s: f32,
    pub approach_speed: f32,
}

#[derive(Debug, Default)]
pub struct Detections {
    pub touches: Vec<Touch>,
    pub kickoffs: Vec<Kickoff>,
    pub fifty_fifties: Vec<FiftyFifty>,
    pub beaten_to_ball: Vec<BeatenToBall>,
}

fn index_of(ids: &[&RemoteId], id: &RemoteId) -> Option<usize> {
    ids.iter().position(|candidate| *candidate == id)
}

const fn team(is_team_0: bool) -> u8 {
    if is_team_0 { 0 } else { 1 }
}

fn touch(event: &TouchClassificationEvent, ids: &[&RemoteId]) -> Option<Touch> {
    Some(Touch {
        frame: event.frame,
        time_s: event.time,
        player_idx: index_of(ids, &event.player)?,
        team: team(event.is_team_0),
        ball_speed_change: event.ball_speed_change,
        kind: event.tag("kind").map(str::to_owned),
        height_band: event.tag("height_band").map(str::to_owned),
        surface: event.tag("surface").map(str::to_owned),
        contested: event.has_tag("contested", "contested"),
    })
}

fn taker(event: &KickoffTakerEvent, ids: &[&RemoteId]) -> Option<KickoffTaker> {
    Some(KickoffTaker {
        player_idx: index_of(ids, &event.player)?,
        team: team(event.is_team_0),
        time_to_ball_s: event.time_to_ball,
        start_boost: event.start_boost,
        boost_used: event.boost_used,
    })
}

fn kickoff(event: &KickoffEvent, ids: &[&RemoteId]) -> Kickoff {
    let (outcome, winner_team) = match event.outcome {
        KickoffOutcome::TeamZeroWin => ("win", Some(0)),
        KickoffOutcome::TeamOneWin => ("win", Some(1)),
        KickoffOutcome::Neutral => ("neutral", None),
        KickoffOutcome::Unknown => ("unknown", None),
    };
    Kickoff {
        start_frame: event.start_frame,
        start_time_s: event.start_time,
        end_frame: event.end_frame,
        end_time_s: event.end_time,
        kickoff_type: serde_json::to_value(event.kickoff_type)
            .ok()
            .and_then(|value| value.as_str().map(str::to_owned))
            .unwrap_or_else(|| "unknown".to_owned()),
        first_touch_frame: event.first_touch_frame,
        first_touch_time_s: event.first_touch_time,
        first_touch_player_idx: event
            .first_touch_player
            .as_ref()
            .and_then(|player| index_of(ids, player)),
        winner_team,
        outcome,
        goal: event.kickoff_goal,
        time_to_goal_s: event.time_to_goal,
        takers: [&event.team_zero_taker, &event.team_one_taker]
            .into_iter()
            .flatten()
            .filter_map(|taker_event| taker(taker_event, ids))
            .collect(),
    }
}

fn fifty_fifty(event: &FiftyFiftyEvent, ids: &[&RemoteId]) -> FiftyFifty {
    let player = |id: &Option<RemoteId>| id.as_ref().and_then(|id| index_of(ids, id));
    FiftyFifty {
        start_frame: event.start_frame,
        start_time_s: event.start_time,
        resolve_frame: event.resolve_frame,
        resolve_time_s: event.resolve_time,
        is_kickoff: event.is_kickoff,
        blue_player_idx: player(&event.team_zero_player),
        orange_player_idx: player(&event.team_one_player),
        winner_team: event.winning_team_is_team_0.map(team),
        possession_team: event.possession_team_is_team_0.map(team),
    }
}

fn beaten(event: &BeatenToBallEvent, ids: &[&RemoteId]) -> Option<BeatenToBall> {
    Some(BeatenToBall {
        frame: event.frame,
        time_s: event.time,
        player_idx: index_of(ids, &event.player)?,
        winner_idx: index_of(ids, &event.winner),
        team: team(event.is_team_0),
        distance_at_touch: event.distance_at_touch,
        margin_s: event.margin_seconds,
        approach_speed: event.approach_speed,
    })
}

fn run(replay: &Replay, ids: &[&RemoteId]) -> Option<Detections> {
    let mut graph = collect_builtin_analysis_graph_for_replay(replay, NODES).ok()?;
    graph.finish().ok()?;
    Some(Detections {
        touches: graph
            .state::<TouchCalculator>()?
            .events()
            .iter()
            .filter_map(|event| touch(event, ids))
            .collect(),
        kickoffs: graph
            .state::<KickoffCalculator>()?
            .events()
            .iter()
            .map(|event| kickoff(event, ids))
            .collect(),
        fifty_fifties: graph
            .state::<FiftyFiftyCalculator>()?
            .events()
            .iter()
            .map(|event| fifty_fifty(event, ids))
            .collect(),
        beaten_to_ball: graph
            .state::<BeatenToBallCalculator>()?
            .events()
            .iter()
            .filter_map(|event| beaten(event, ids))
            .collect(),
    })
}

/// The detections, or `None` when the detectors fail or panic on this replay. `ids` are the
/// roster's players, in `player_idx` order.
///
/// A caught panic stays silent: `main`'s hook would print that the parser stopped, when it goes on
/// and succeeds. `rl-parse` runs on one thread, so swapping the hook for this call is safe.
pub fn detect(replay: &Replay, ids: &[&RemoteId]) -> Option<Detections> {
    let hook = std::panic::take_hook();
    std::panic::set_hook(Box::new(|_| {}));
    let found = catch_unwind(AssertUnwindSafe(|| run(replay, ids)))
        .ok()
        .flatten();
    std::panic::set_hook(hook);
    found
}
