//! T0.7: what do anonymized players look like, and does the header's PlayerID hold the Epic id?
//! Values are only compared in memory: booleans and field names are printed, never a name or an id.

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::path::PathBuf;

use boxcars::{Attribute, HeaderProp, ParserBuilder, RemoteId};

#[derive(Default)]
struct Pri {
    name: Option<String>,
    anonymized_name: Option<String>,
    to_opponents: bool,
    to_teammates: bool,
    epic_id: Option<String>,
    kind: &'static str,
}

fn strings(prop: &HeaderProp, out: &mut Vec<String>) {
    match prop {
        HeaderProp::Str(s) | HeaderProp::Name(s) => out.push(s.clone()),
        HeaderProp::QWord(q) => out.push(q.to_string()),
        HeaderProp::Struct { fields, .. } => fields.iter().for_each(|(_, v)| strings(v, out)),
        HeaderProp::Array(rows) => rows.iter().flatten().for_each(|(_, v)| strings(v, out)),
        _ => {}
    }
}

fn shape(prop: &HeaderProp) -> String {
    match prop {
        HeaderProp::Struct { name, fields } => {
            let inner: Vec<String> = fields.iter().map(|(k, v)| format!("{k}:{}", shape(v))).collect();
            format!("{name}{{{}}}", inner.join(","))
        }
        HeaderProp::Str(_) => "str".into(),
        HeaderProp::Name(_) => "name".into(),
        HeaderProp::QWord(_) => "qword".into(),
        HeaderProp::Int(_) => "int".into(),
        HeaderProp::Byte { .. } => "byte".into(),
        HeaderProp::Bool(_) => "bool".into(),
        HeaderProp::Float(_) => "float".into(),
        HeaderProp::Array(_) => "array".into(),
    }
}

pub fn identity(files: &[PathBuf]) {
    let mut rows: BTreeMap<String, u32> = BTreeMap::new();
    let mut shapes: BTreeMap<String, u32> = BTreeMap::new();
    let mut player_id: BTreeMap<String, u32> = BTreeMap::new();
    for file in files {
        let bytes = std::fs::read(file).expect("read");
        let Ok(replay) = ParserBuilder::new(&bytes).must_parse_network_data().parse() else { continue };
        let mut pris: HashMap<i32, Pri> = HashMap::new();
        if let Some(frames) = &replay.network_frames {
            for frame in &frames.frames {
                for update in &frame.updated_actors {
                    let Some(object) = replay.objects.get(update.object_id.0 as usize) else { continue };
                    match (object.as_str(), &update.attribute) {
                        ("Engine.PlayerReplicationInfo:PlayerName", Attribute::String(s)) => {
                            pris.entry(update.actor_id.0).or_default().name = Some(s.clone());
                        }
                        ("TAGame.PRI_TA:AnonymizedName", Attribute::String(s)) => {
                            pris.entry(update.actor_id.0).or_default().anonymized_name = Some(s.clone());
                        }
                        ("TAGame.PRI_TA:bAnonymizeToOpponents", Attribute::Boolean(b)) => {
                            pris.entry(update.actor_id.0).or_default().to_opponents |= *b;
                        }
                        ("TAGame.PRI_TA:bAnonymizeToTeammates", Attribute::Boolean(b)) => {
                            pris.entry(update.actor_id.0).or_default().to_teammates |= *b;
                        }
                        ("Engine.PlayerReplicationInfo:UniqueId", Attribute::UniqueId(id)) => {
                            let entry = pris.entry(update.actor_id.0).or_default();
                            match &id.remote_id {
                                RemoteId::Epic(value) => {
                                    entry.kind = "epic";
                                    entry.epic_id = Some(value.to_ascii_lowercase());
                                }
                                RemoteId::Steam(_) => entry.kind = "steam",
                                RemoteId::Xbox(_) => entry.kind = "xbox",
                                RemoteId::PlayStation(_) | RemoteId::PsyNet(_) => entry.kind = "psn",
                                RemoteId::Switch(_) => entry.kind = "switch",
                                _ => entry.kind = "other",
                            }
                        }
                        _ => {}
                    }
                }
            }
        }

        let entries: Vec<&Vec<(String, HeaderProp)>> = replay
            .properties
            .iter()
            .find(|(k, _)| k == "PlayerStats")
            .and_then(|(_, v)| v.as_array())
            .map(|rows| rows.iter().collect())
            .unwrap_or_default();
        let header_names: BTreeSet<String> = entries
            .iter()
            .filter_map(|e| e.iter().find(|(k, _)| k == "Name"))
            .filter_map(|(_, v)| v.as_string().map(str::to_owned))
            .collect();
        let network_epic: BTreeSet<&String> = pris.values().filter_map(|p| p.epic_id.as_ref()).collect();

        for pri in pris.values() {
            let Some(name) = &pri.name else { continue };
            let key = format!(
                "kind={} to_opponents={} to_teammates={} has_id={} header_name_is_player_name={} header_name_is_anonymized={}",
                pri.kind,
                pri.to_opponents,
                pri.to_teammates,
                !pri.kind.is_empty(),
                header_names.contains(name),
                pri.anonymized_name.as_ref().is_some_and(|a| header_names.contains(a)),
            );
            *rows.entry(key).or_default() += 1;
        }

        for entry in &entries {
            let Some((_, id)) = entry.iter().find(|(k, _)| k == "PlayerID") else {
                *player_id.entry("no PlayerID".into()).or_default() += 1;
                continue;
            };
            *shapes.entry(shape(id)).or_default() += 1;
            let platform = entry.iter().find(|(k, _)| k == "Platform").and_then(|(_, v)| match v {
                HeaderProp::Byte { value, .. } => value.clone(),
                _ => None,
            });
            let name = entry.iter().find(|(k, _)| k == "Name").and_then(|(_, v)| v.as_string());
            let mut values = Vec::new();
            strings(id, &mut values);
            let own_epic = pris.values().find(|p| p.name.as_deref() == name).and_then(|p| p.epic_id.as_ref());
            let holds_own_epic = own_epic.is_some_and(|e| values.iter().any(|v| v.eq_ignore_ascii_case(e)));
            let holds_any_epic = values.iter().any(|v| network_epic.contains(&v.to_ascii_lowercase()));
            *player_id
                .entry(format!("platform={platform:?} own_network_epic_known={} holds_own_epic={holds_own_epic} holds_any_epic={holds_any_epic}", own_epic.is_some()))
                .or_default() += 1;
        }
    }
    println!("--- network players");
    rows.iter().for_each(|(k, v)| println!("{v:>4}  {k}"));
    println!("--- PlayerID shapes");
    shapes.iter().for_each(|(k, v)| println!("{v:>4}  {k}"));
    println!("--- PlayerID against the network Epic id");
    player_id.iter().for_each(|(k, v)| println!("{v:>4}  {k}"));
}
