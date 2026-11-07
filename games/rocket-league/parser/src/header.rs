//! `header.json`: what the replay's header says, without touching the network stream.

use boxcars::{HeaderProp, ParserBuilder, Replay};
use serde::Serialize;

use crate::error::Failure;
use crate::identity;

pub const SCHEMA_VERSION: u32 = 1;
pub const PARSER_VERSION: &str = env!("CARGO_PKG_VERSION");

/// The game class every replay starts with, a few bytes into the file.
const REPLAY_CLASS_PREFIX: &[u8] = b"TAGame.Replay_";
const CLASS_SEARCH_BYTES: usize = 256;

/// `MatchStartEpoch` outside this range (years 2000 to 2100) is not trusted.
const EPOCH_RANGE: std::ops::Range<u64> = 946_684_800..4_102_444_800;

#[derive(Debug, Serialize)]
pub struct Header {
    pub schema_version: u32,
    pub parser_version: &'static str,
    pub game_build: Option<String>,
    pub build_id: Option<i64>,
    pub changelist: Option<i64>,
    pub replay_version: ReplayVersion,
    pub game_class: String,
    pub match_guid: Option<String>,
    pub replay_id: Option<String>,
    pub map: Option<String>,
    pub played_at: Option<String>,
    pub played_at_source: Option<&'static str>,
    pub duration_s: Option<f32>,
    pub match_type: Option<String>,
    /// Only the network stream knows it: see `events.json`.
    pub playlist: Option<String>,
    pub team_size: Option<i64>,
    pub score: Score,
    pub goals: Vec<HeaderGoal>,
    pub players: Vec<HeaderPlayer>,
}

#[derive(Debug, Serialize)]
pub struct ReplayVersion {
    pub major: i32,
    pub minor: i32,
    pub net: Option<i32>,
}

#[derive(Debug, Serialize)]
pub struct Score {
    pub blue: i64,
    pub orange: i64,
}

#[derive(Debug, Serialize)]
pub struct HeaderGoal {
    pub frame: i64,
    /// Estimated from the frame number: the network stream gives the exact time.
    pub time_s: Option<f32>,
    pub player_name: Option<String>,
    pub team: Option<i64>,
}

#[derive(Debug, Serialize)]
pub struct HeaderPlayer {
    pub platform: &'static str,
    pub platform_id: Option<String>,
    pub name: String,
    pub team: Option<i64>,
    pub score: i64,
    pub goals: i64,
    pub assists: i64,
    pub saves: i64,
    pub shots: i64,
    pub is_bot: bool,
}

/// A replay names its class near the start of the file: cheap to check before parsing.
pub fn looks_like_replay(bytes: &[u8]) -> bool {
    let head = &bytes[..bytes.len().min(CLASS_SEARCH_BYTES)];
    head.windows(REPLAY_CLASS_PREFIX.len())
        .any(|window| window == REPLAY_CLASS_PREFIX)
}

/// Reads the header and the body's tables, checking both CRCs. A network stream the parser does
/// not understand does not fail here: that is the "header OK, network KO" case.
pub fn parse(bytes: &[u8]) -> Result<Replay, Failure> {
    if !looks_like_replay(bytes) {
        return Err(Failure::NotAReplay);
    }
    ParserBuilder::new(bytes)
        .never_parse_network_data()
        .always_check_crc()
        .parse()
        .map_err(|error| Failure::from_parse_error(&error))
}

fn prop<'a>(props: &'a [(String, HeaderProp)], key: &str) -> Option<&'a HeaderProp> {
    props
        .iter()
        .find(|(name, _)| name == key)
        .map(|(_, value)| value)
}

fn text(props: &[(String, HeaderProp)], key: &str) -> Option<String> {
    match prop(props, key)? {
        HeaderProp::Str(value) | HeaderProp::Name(value) => Some(value.clone()),
        _ => None,
    }
}

fn integer(props: &[(String, HeaderProp)], key: &str) -> Option<i64> {
    match prop(props, key)? {
        HeaderProp::Int(value) => Some(i64::from(*value)),
        HeaderProp::QWord(value) => i64::try_from(*value).ok(),
        _ => None,
    }
}

fn float(props: &[(String, HeaderProp)], key: &str) -> Option<f32> {
    match prop(props, key)? {
        HeaderProp::Float(value) if value.is_finite() => Some(*value),
        _ => None,
    }
}

fn flag(props: &[(String, HeaderProp)], key: &str) -> bool {
    matches!(prop(props, key), Some(HeaderProp::Bool(true)))
}

fn entries<'a>(props: &'a [(String, HeaderProp)], key: &str) -> &'a [Vec<(String, HeaderProp)>] {
    match prop(props, key) {
        Some(HeaderProp::Array(rows)) => rows,
        _ => &[],
    }
}

/// ISO 8601 from days since the epoch and seconds in the day (Howard Hinnant's civil_from_days).
fn iso_from_epoch(epoch: u64) -> String {
    let days = (epoch / 86_400) as i64 + 719_468;
    let seconds = epoch % 86_400;
    let era = days.div_euclid(146_097);
    let day_of_era = days.rem_euclid(146_097);
    let year_of_era =
        (day_of_era - day_of_era / 1_460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let shifted_month = (5 * day_of_year + 2) / 153;
    let day = day_of_year - (153 * shifted_month + 2) / 5 + 1;
    let month = if shifted_month < 10 {
        shifted_month + 3
    } else {
        shifted_month - 9
    };
    let year = year_of_era + era * 400 + i64::from(month <= 2);
    format!(
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}Z",
        seconds / 3_600,
        seconds % 3_600 / 60,
        seconds % 60
    )
}

/// The header's `Date`, like `2026-04-28 18-07-32`, is the recorder's local clock: its time zone
/// is unknown, so the result carries no offset.
fn iso_from_local_date(value: &str) -> Option<String> {
    let digits: Vec<&str> = value.split(|c: char| !c.is_ascii_digit()).collect();
    let [year, month, day, hour, minute, second] = digits.as_slice() else {
        return None;
    };
    let widths = [
        (year, 4),
        (month, 2),
        (day, 2),
        (hour, 2),
        (minute, 2),
        (second, 2),
    ];
    if widths.iter().any(|(part, width)| part.len() != *width) {
        return None;
    }
    Some(format!("{year}-{month}-{day}T{hour}:{minute}:{second}"))
}

fn played_at(props: &[(String, HeaderProp)]) -> (Option<String>, Option<&'static str>) {
    let epoch = match prop(props, "MatchStartEpoch") {
        Some(HeaderProp::QWord(value)) if EPOCH_RANGE.contains(value) => Some(*value),
        _ => None,
    };
    if let Some(epoch) = epoch {
        return (Some(iso_from_epoch(epoch)), Some("epoch"));
    }
    match text(props, "Date").as_deref().and_then(iso_from_local_date) {
        Some(date) => (Some(date), Some("date_without_timezone")),
        None => (None, None),
    }
}

/// `TotalSecondsPlayed` when the replay has it. `NumFrames / RecordFPS` otherwise, which runs
/// about 16 % short: frames are not evenly spaced.
fn duration(props: &[(String, HeaderProp)]) -> Option<f32> {
    if let Some(total) = float(props, "TotalSecondsPlayed").filter(|value| *value > 0.0) {
        return Some(total);
    }
    let frames = integer(props, "NumFrames")?;
    let fps = float(props, "RecordFPS").filter(|value| *value > 0.0)?;
    Some(frames as f32 / fps)
}

/// Epic players hold no `OnlineID`: their id is in the `PlayerID` struct of recent replays.
fn epic_id(entry: &[(String, HeaderProp)]) -> Option<String> {
    let HeaderProp::Struct { fields, .. } = prop(entry, "PlayerID")? else {
        return None;
    };
    text(fields, "EpicAccountId")
        .as_deref()
        .and_then(identity::normalize_epic)
}

fn player(entry: &[(String, HeaderProp)]) -> HeaderPlayer {
    let is_bot = flag(entry, "bBot");
    let platform_name = match prop(entry, "Platform") {
        Some(HeaderProp::Byte {
            value: Some(value), ..
        }) => value.as_str(),
        _ => "",
    };
    let platform = identity::platform_from_header(platform_name, is_bot);
    let platform_id = match platform {
        identity::BOT | identity::UNKNOWN => None,
        identity::EPIC => epic_id(entry),
        _ => match prop(entry, "OnlineID") {
            Some(HeaderProp::QWord(value)) if *value != 0 => Some(value.to_string()),
            _ => None,
        },
    };
    let number = |key: &str| integer(entry, key).unwrap_or(0);
    HeaderPlayer {
        platform,
        platform_id,
        name: text(entry, "Name").unwrap_or_default(),
        team: integer(entry, "Team"),
        score: number("Score"),
        goals: number("Goals"),
        assists: number("Assists"),
        saves: number("Saves"),
        shots: number("Shots"),
        is_bot,
    }
}

/// The people who played. Spectators of a private match are listed too, with team -1 and nothing
/// on the network stream: they did not play, and their ids have no reason to be kept.
fn players(props: &[(String, HeaderProp)]) -> Vec<HeaderPlayer> {
    entries(props, "PlayerStats")
        .iter()
        .map(|entry| player(entry))
        .filter(|player| matches!(player.team, None | Some(0 | 1)))
        .collect()
}

pub fn extract(replay: &Replay) -> Header {
    let props = &replay.properties;
    let fps = float(props, "RecordFPS").filter(|value| *value > 0.0);
    let goals = entries(props, "Goals")
        .iter()
        .map(|entry| {
            let frame = integer(entry, "frame").unwrap_or(0);
            HeaderGoal {
                frame,
                time_s: fps.map(|fps| frame as f32 / fps),
                player_name: text(entry, "PlayerName"),
                team: integer(entry, "PlayerTeam"),
            }
        })
        .collect();
    let (played_at, played_at_source) = played_at(props);
    Header {
        schema_version: SCHEMA_VERSION,
        parser_version: PARSER_VERSION,
        game_build: text(props, "BuildVersion"),
        build_id: integer(props, "BuildID"),
        changelist: integer(props, "Changelist"),
        replay_version: ReplayVersion {
            major: replay.major_version,
            minor: replay.minor_version,
            net: replay.net_version,
        },
        game_class: replay.game_type.clone(),
        // Both spellings exist in real replays.
        match_guid: text(props, "MatchGUID").or_else(|| text(props, "MatchGuid")),
        replay_id: text(props, "Id"),
        map: text(props, "MapName"),
        played_at,
        played_at_source,
        duration_s: duration(props),
        match_type: text(props, "MatchType"),
        playlist: None,
        team_size: integer(props, "TeamSize"),
        // A team that scored nothing has no property at all.
        score: Score {
            blue: integer(props, "Team0Score").unwrap_or(0),
            orange: integer(props, "Team1Score").unwrap_or(0),
        },
        goals,
        players: players(props),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn props(items: Vec<(&str, HeaderProp)>) -> Vec<(String, HeaderProp)> {
        items
            .into_iter()
            .map(|(key, value)| (key.to_owned(), value))
            .collect()
    }

    #[test]
    fn replay_prefix_check() {
        assert!(looks_like_replay(
            b"\x01\x02\x03\x04TAGame.Replay_Soccar_TA\0"
        ));
        assert!(!looks_like_replay(b""));
        assert!(!looks_like_replay(&[0u8; 4096]));
    }

    #[test]
    fn epoch_to_iso() {
        assert_eq!(iso_from_epoch(0), "1970-01-01T00:00:00Z");
        assert_eq!(iso_from_epoch(951_782_400), "2000-02-29T00:00:00Z");
        assert_eq!(iso_from_epoch(1_777_399_652), "2026-04-28T18:07:32Z");
        assert_eq!(iso_from_epoch(4_102_444_799), "2099-12-31T23:59:59Z");
    }

    #[test]
    fn local_date_to_iso() {
        assert_eq!(
            iso_from_local_date("2026-04-28 18-07-32").unwrap(),
            "2026-04-28T18:07:32"
        );
        assert_eq!(
            iso_from_local_date("2016-07-21:12:00:01").unwrap(),
            "2016-07-21T12:00:01"
        );
        assert_eq!(iso_from_local_date("not a date"), None);
        assert_eq!(iso_from_local_date("2026-04-28"), None);
        assert_eq!(iso_from_local_date("26-04-28 18-07-32"), None);
    }

    #[test]
    fn played_at_prefers_a_plausible_epoch() {
        let both = props(vec![
            ("MatchStartEpoch", HeaderProp::QWord(1_777_399_652)),
            ("Date", HeaderProp::Str("2020-01-01 00-00-00".to_owned())),
        ]);
        assert_eq!(
            played_at(&both),
            (Some("2026-04-28T18:07:32Z".to_owned()), Some("epoch"))
        );
        let absurd = props(vec![
            ("MatchStartEpoch", HeaderProp::QWord(12)),
            ("Date", HeaderProp::Str("2020-01-01 00-00-00".to_owned())),
        ]);
        assert_eq!(
            played_at(&absurd),
            (
                Some("2020-01-01T00:00:00".to_owned()),
                Some("date_without_timezone")
            )
        );
        assert_eq!(played_at(&props(vec![])), (None, None));
    }

    #[test]
    fn duration_prefers_seconds_played() {
        let both = props(vec![
            ("TotalSecondsPlayed", HeaderProp::Float(310.5)),
            ("NumFrames", HeaderProp::Int(3000)),
            ("RecordFPS", HeaderProp::Float(30.0)),
        ]);
        assert_eq!(duration(&both), Some(310.5));
        let frames = props(vec![
            ("NumFrames", HeaderProp::Int(3000)),
            ("RecordFPS", HeaderProp::Float(30.0)),
        ]);
        assert_eq!(duration(&frames), Some(100.0));
        assert_eq!(
            duration(&props(vec![("NumFrames", HeaderProp::Int(3000))])),
            None
        );
    }

    #[test]
    fn spectators_are_not_players() {
        let entry = |team: i32| {
            vec![
                ("Team".to_owned(), HeaderProp::Int(team)),
                ("Name".to_owned(), HeaderProp::Str(format!("team {team}"))),
            ]
        };
        let props = props(vec![(
            "PlayerStats",
            HeaderProp::Array(vec![entry(0), entry(-1), entry(1)]),
        )]);
        let names: Vec<String> = players(&props).into_iter().map(|p| p.name).collect();
        assert_eq!(names, ["team 0", "team 1"]);
    }

    fn platform(value: &str) -> HeaderProp {
        HeaderProp::Byte {
            kind: "OnlinePlatform".to_owned(),
            value: Some(format!("OnlinePlatform_{value}")),
        }
    }

    #[test]
    fn players_by_platform() {
        let epic = props(vec![
            ("Platform", platform("Epic")),
            ("OnlineID", HeaderProp::QWord(0)),
            ("Name", HeaderProp::Str("a".to_owned())),
            (
                "PlayerID",
                HeaderProp::Struct {
                    name: "UniqueNetId".to_owned(),
                    fields: props(vec![(
                        "EpicAccountId",
                        HeaderProp::Str("ABC123".to_owned()),
                    )]),
                },
            ),
        ]);
        let parsed = player(&epic);
        assert_eq!(
            (parsed.platform, parsed.platform_id.as_deref()),
            ("epic", Some("abc123"))
        );

        let old_epic = props(vec![
            ("Platform", platform("Epic")),
            ("OnlineID", HeaderProp::QWord(0)),
        ]);
        assert_eq!(player(&old_epic).platform_id, None);

        let steam = props(vec![
            ("Platform", platform("Steam")),
            ("OnlineID", HeaderProp::QWord(42)),
        ]);
        assert_eq!(player(&steam).platform_id.as_deref(), Some("42"));

        let switch = props(vec![
            ("Platform", platform("NNX")),
            ("OnlineID", HeaderProp::QWord(7)),
        ]);
        assert_eq!(player(&switch).platform, "switch");

        let bot = props(vec![
            ("Platform", platform("Unknown")),
            ("bBot", HeaderProp::Bool(true)),
        ]);
        let parsed = player(&bot);
        assert_eq!(
            (parsed.platform, parsed.platform_id, parsed.is_bot),
            ("bot", None, true)
        );
    }
}
