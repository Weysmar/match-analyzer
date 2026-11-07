//! Can rl-parse get the game phases and the pickups without the full analysis graph?
//! Own Collector around subtr-actor's public LivePlayTracker, and the "boost" stats module alone.

use std::collections::HashMap;
use std::path::Path;
use std::time::Instant;

use boxcars::ParserBuilder;
use serde_json::json;
use subtr_actor::{
    Collector, FrameEventsState, GameplayPhase, GameplayState, LivePlayTracker, ProcessorView,
    ReplayProcessor, StatsCollector, StatsFrameResolution, StatsTimelineEventCollector,
    SubtrActorResult, TimeAdvance,
};

#[derive(Default)]
struct PhaseCollector {
    tracker: LivePlayTracker,
    phases: Vec<(u32, GameplayPhase)>,
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
            team_zero_score: scores.map(|s| s.0),
            team_one_score: scores.map(|s| s.1),
            ..Default::default()
        };
        let events = FrameEventsState {
            goal_events: processor.current_frame_goal_events().to_vec(),
            ..Default::default()
        };
        let state = self.tracker.state_parts(&gameplay, &events);
        self.phases.push((current_time.to_bits(), state.gameplay_phase));
        Ok(TimeAdvance::NextFrame)
    }
}

pub fn light(path: &Path, compare: bool) {
    let bytes = std::fs::read(path).expect("read");
    let replay = ParserBuilder::new(&bytes).must_parse_network_data().parse().expect("parse");
    let start = Instant::now();
    let mut collector = PhaseCollector::default();
    ReplayProcessor::new(&replay).expect("processor").process_all(&mut [&mut collector]).expect("process");
    let phase_ms = start.elapsed().as_millis() as u64;

    let (mut agree, mut total) = (0u64, 0u64);
    let mut scaffold_ms = None;
    if compare {
        let start = Instant::now();
        let scaffold = StatsTimelineEventCollector::new()
            .with_frame_resolution(StatsFrameResolution::EveryFrame)
            .get_replay_stats_timeline_scaffold(&replay)
            .expect("scaffold");
        scaffold_ms = Some(start.elapsed().as_millis() as u64);
        let reference: HashMap<u32, GameplayPhase> =
            scaffold.frames.iter().map(|f| (f.time.to_bits(), f.gameplay_phase)).collect();
        for (time, phase) in &collector.phases {
            if let Some(expected) = reference.get(time) {
                total += 1;
                agree += u64::from(expected == phase);
            }
        }
    }

    let start = Instant::now();
    let boost = StatsCollector::with_builtin_module_names(["boost"])
        .expect("module")
        .get_stats(&replay);
    let boost_ms = start.elapsed().as_millis() as u64;
    let pickups = boost
        .ok()
        .and_then(|s| serde_json::to_value(s).ok())
        .and_then(|v| v["modules"]["boost"]["pickup_events"].as_array().map(Vec::len));
    println!("{}", json!({
        "frames": collector.phases.len(),
        "phase_ms": phase_ms,
        "scaffold_ms": scaffold_ms,
        "phase_agree": agree,
        "phase_compared": total,
        "boost_only_ms": boost_ms,
        "pickups": pickups,
    }));
}
