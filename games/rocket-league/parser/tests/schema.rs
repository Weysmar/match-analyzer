//! `frames.schema.json` is the source of truth for the Parquet writer. No replay needed.

use std::path::Path;

use arrow::datatypes::DataType;
use rl_parse::events::EVENTS_SCHEMA_VERSION;
use rl_parse::header::SCHEMA_VERSION;
use rl_parse::output::frames_schema;
use serde_json::Value;

fn document(name: &str) -> Value {
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../../packages/schemas")
        .join(name);
    serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap()
}

fn type_name(kind: &DataType) -> &'static str {
    match kind {
        DataType::UInt32 => "uint32",
        DataType::UInt8 => "uint8",
        DataType::Float32 => "float32",
        DataType::Boolean => "boolean",
        other => panic!("a type the schema does not know: {other}"),
    }
}

#[test]
fn the_parquet_writer_follows_the_schema() {
    let written = frames_schema();
    let schema = document("frames.schema.json");
    let columns = schema["columns"].as_array().unwrap();
    let names = |value: &Value| value["name"].as_str().unwrap().to_owned();
    assert_eq!(
        written
            .fields()
            .iter()
            .map(|field| field.name().clone())
            .collect::<Vec<_>>(),
        columns.iter().map(names).collect::<Vec<_>>()
    );
    for (field, column) in written.fields().iter().zip(columns) {
        assert_eq!(
            type_name(field.data_type()),
            column["type"],
            "{}",
            field.name()
        );
        assert_eq!(field.is_nullable(), column["nullable"], "{}", field.name());
    }
}

#[test]
fn schema_versions_agree() {
    assert_eq!(
        document("header.schema.json")["properties"]["schema_version"]["const"],
        SCHEMA_VERSION
    );
    assert_eq!(
        document("events.schema.json")["properties"]["schema_version"]["const"],
        EVENTS_SCHEMA_VERSION
    );
    assert_eq!(
        document("frames.schema.json")["schema_version"],
        SCHEMA_VERSION
    );
}
