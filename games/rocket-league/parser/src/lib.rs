//! `rl-parse`: turns a replay file into `header.json`, `frames.parquet` and `events.json`.
//! The contracts are in step 2 of `docs/PLAN.md`.

pub mod detections;
pub mod error;
pub mod events;
pub mod frames;
pub mod header;
pub mod identity;
pub mod output;
