//! Command line of `rl-parse`. Exit codes and outputs: step 2 of `docs/PLAN.md`.

use std::path::PathBuf;

use clap::{ArgGroup, Parser, error::ErrorKind};
use rl_parse::error::Failure;
use rl_parse::{events, frames, header, output};

#[derive(Parser)]
#[command(
    name = "rl-parse",
    version,
    about = "Turns a replay into header.json, or frames.parquet and events.json"
)]
#[command(group(ArgGroup::new("mode").required(true).args(["header", "frames"])))]
struct Cli {
    /// Read the header only, without the network stream
    #[arg(long)]
    header: bool,
    /// Decode the network stream
    #[arg(long)]
    frames: bool,
    /// The replay file
    #[arg(long)]
    input: PathBuf,
    /// Where to write header.json (with --header)
    #[arg(long)]
    output: Option<PathBuf>,
    /// Where to write frames.parquet and events.json (with --frames)
    #[arg(long)]
    output_dir: Option<PathBuf>,
    /// Optional cap on the frame rate. By default, every frame of the replay is kept
    #[arg(long, value_parser = positive_fps)]
    fps: Option<f32>,
}

fn positive_fps(value: &str) -> Result<f32, String> {
    match value.parse::<f32>() {
        Ok(fps) if fps.is_finite() && fps > 0.0 => Ok(fps),
        _ => Err("a positive number is expected".to_owned()),
    }
}

/// Each mode takes its own options, and only those.
const fn is_valid(cli: &Cli) -> bool {
    if cli.header {
        cli.output.is_some() && cli.output_dir.is_none() && cli.fps.is_none()
    } else {
        cli.output_dir.is_some() && cli.output.is_none()
    }
}

fn run(cli: &Cli) -> Result<(), Failure> {
    if !is_valid(cli) {
        return Err(Failure::Usage);
    }
    let bytes = std::fs::read(&cli.input).map_err(|_| Failure::NotAReplay)?;
    if cli.header {
        let replay = header::parse(&bytes)?;
        let path = cli.output.as_ref().ok_or(Failure::Usage)?;
        return output::write_json(path, &header::extract(&replay));
    }
    let replay = frames::parse(&bytes)?;
    let collected = frames::collect(&replay, cli.fps)?;
    let directory = cli.output_dir.as_ref().ok_or(Failure::Usage)?;
    std::fs::create_dir_all(directory).map_err(|_| Failure::OutputError)?;
    output::write_frames(&directory.join("frames.parquet"), &collected)?;
    output::write_json(
        &directory.join("events.json"),
        &events::extract(&replay, &collected, cli.fps),
    )
}

fn main() {
    // A panic's message could quote a player's name: only a fixed line goes out. The exit code
    // stays Rust's 101.
    std::panic::set_hook(Box::new(|_| {
        eprintln!(r#"{{"code":"panic","message":"the parser stopped unexpectedly"}}"#);
    }));
    let cli = match Cli::try_parse() {
        Ok(cli) => cli,
        Err(error)
            if matches!(
                error.kind(),
                ErrorKind::DisplayHelp | ErrorKind::DisplayVersion
            ) =>
        {
            print!("{error}");
            return;
        }
        Err(_) => fail(Failure::Usage),
    };
    if let Err(failure) = run(&cli) {
        fail(failure);
    }
}

fn fail(failure: Failure) -> ! {
    eprintln!("{}", failure.to_json());
    std::process::exit(failure.exit_code());
}
