//! Player identity, from the header and from the network stream.

use std::collections::HashMap;

use boxcars::{Attribute, RemoteId, Replay};

pub const STEAM: &str = "steam";
pub const EPIC: &str = "epic";
pub const PSN: &str = "psn";
pub const XBOX: &str = "xbox";
pub const SWITCH: &str = "switch";
pub const BOT: &str = "bot";
pub const UNKNOWN: &str = "unknown";

/// Shown when a player asked for anonymity and the replay gives no anonymized name.
pub const ANONYMOUS_NAME: &str = "anonymous";

/// The platform named in the header's `PlayerStats`. `Dingo` is Xbox, `NNX` is Switch.
pub fn platform_from_header(value: &str, is_bot: bool) -> &'static str {
    if is_bot {
        return BOT;
    }
    match value {
        "OnlinePlatform_Steam" => STEAM,
        "OnlinePlatform_Epic" => EPIC,
        "OnlinePlatform_PS4" => PSN,
        "OnlinePlatform_Dingo" => XBOX,
        "OnlinePlatform_NNX" => SWITCH,
        _ => UNKNOWN,
    }
}

/// The platform and id of a network identity. Zero or empty ids become `None`: old replays hold
/// sentinel values that would merge different players.
pub fn from_remote_id(id: &RemoteId) -> (&'static str, Option<String>) {
    fn number(value: u64) -> Option<String> {
        (value != 0).then(|| value.to_string())
    }
    match id {
        RemoteId::Steam(value) => (STEAM, number(*value)),
        RemoteId::Epic(value) => (EPIC, normalize_epic(value)),
        RemoteId::Xbox(value) => (XBOX, number(*value)),
        RemoteId::PlayStation(value) => (PSN, number(value.online_id)),
        RemoteId::PsyNet(value) => (PSN, number(value.online_id)),
        RemoteId::Switch(value) => (SWITCH, number(value.online_id)),
        _ => (UNKNOWN, None),
    }
}

/// Epic account ids compare in lowercase, as the OAuth `account_id` does.
pub fn normalize_epic(value: &str) -> Option<String> {
    let value = value.trim();
    (!value.is_empty()).then(|| value.to_ascii_lowercase())
}

/// What a player replicated about anonymity. Flags are sticky: once asked, always respected.
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct Anonymity {
    pub requested: bool,
    pub anonymized_name: Option<String>,
}

/// Anonymity by player, keyed like the processor's players. The flags and the anonymized name
/// live on the same replicated actor as the player's unique id.
pub fn anonymity_by_player(replay: &Replay) -> HashMap<RemoteId, Anonymity> {
    let mut by_actor: HashMap<i32, (Anonymity, Option<RemoteId>)> = HashMap::new();
    let Some(frames) = &replay.network_frames else {
        return HashMap::new();
    };
    for frame in &frames.frames {
        for update in &frame.updated_actors {
            let Some(object) = replay.objects.get(update.object_id.0 as usize) else {
                continue;
            };
            match (object.as_str(), &update.attribute) {
                (
                    "TAGame.PRI_TA:bAnonymizeToOpponents" | "TAGame.PRI_TA:bAnonymizeToTeammates",
                    Attribute::Boolean(true),
                ) => by_actor.entry(update.actor_id.0).or_default().0.requested = true,
                ("TAGame.PRI_TA:AnonymizedName", Attribute::String(name)) => {
                    by_actor
                        .entry(update.actor_id.0)
                        .or_default()
                        .0
                        .anonymized_name = Some(name.clone());
                }
                ("Engine.PlayerReplicationInfo:UniqueId", Attribute::UniqueId(id)) => {
                    by_actor.entry(update.actor_id.0).or_default().1 = Some(id.remote_id.clone());
                }
                _ => {}
            }
        }
    }
    let mut players: HashMap<RemoteId, Anonymity> = HashMap::new();
    for (anonymity, id) in by_actor.into_values() {
        let Some(id) = id else { continue };
        let entry = players.entry(id).or_default();
        entry.requested |= anonymity.requested;
        if anonymity.anonymized_name.is_some() {
            entry.anonymized_name = anonymity.anonymized_name;
        }
    }
    players
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn header_platforms() {
        assert_eq!(platform_from_header("OnlinePlatform_Steam", false), STEAM);
        assert_eq!(platform_from_header("OnlinePlatform_Epic", false), EPIC);
        assert_eq!(platform_from_header("OnlinePlatform_PS4", false), PSN);
        assert_eq!(platform_from_header("OnlinePlatform_Dingo", false), XBOX);
        assert_eq!(platform_from_header("OnlinePlatform_NNX", false), SWITCH);
        assert_eq!(
            platform_from_header("OnlinePlatform_Unknown", false),
            UNKNOWN
        );
        assert_eq!(platform_from_header("OnlinePlatform_Unknown", true), BOT);
        assert_eq!(platform_from_header("OnlinePlatform_Steam", true), BOT);
    }

    #[test]
    fn network_ids() {
        assert_eq!(
            from_remote_id(&RemoteId::Steam(76561190000000000)),
            (STEAM, Some("76561190000000000".to_owned()))
        );
        assert_eq!(from_remote_id(&RemoteId::Steam(0)), (STEAM, None));
        assert_eq!(
            from_remote_id(&RemoteId::Epic("ABCdef".to_owned())),
            (EPIC, Some("abcdef".to_owned()))
        );
        assert_eq!(from_remote_id(&RemoteId::Epic(String::new())), (EPIC, None));
        assert_eq!(
            from_remote_id(&RemoteId::Xbox(7)),
            (XBOX, Some("7".to_owned()))
        );
        assert_eq!(from_remote_id(&RemoteId::SplitScreen(1)), (UNKNOWN, None));
    }
}
