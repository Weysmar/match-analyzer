//! The errors `rl-parse` reports. Each one is a fixed code and a fixed message: errors from
//! subtr-actor can quote whole header entries, so their text must never reach the output.

use boxcars::ParseError;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Failure {
    /// Bad command line. A bug in the caller.
    Usage,
    /// The file is not a replay: the upload is rejected.
    NotAReplay,
    /// A replay that fails its checks: the upload is rejected.
    Corrupt,
    /// The header is readable but the network stream is not, typically after a game patch.
    NetworkFailed,
    /// The network stream is readable, but subtr-actor cannot make sense of it.
    ProcessorFailed,
    /// A game mode the V1 metrics do not cover: stats of the header only, no retry.
    UnsupportedMode,
    /// The output could not be written: worth retrying.
    OutputError,
}

impl Failure {
    pub const fn exit_code(self) -> i32 {
        match self {
            Failure::Usage => 2,
            Failure::NotAReplay => 10,
            Failure::Corrupt => 11,
            Failure::NetworkFailed => 12,
            Failure::ProcessorFailed => 13,
            Failure::UnsupportedMode => 14,
            Failure::OutputError => 15,
        }
    }

    pub const fn code(self) -> &'static str {
        match self {
            Failure::Usage => "usage",
            Failure::NotAReplay => "not_a_replay",
            Failure::Corrupt => "corrupt",
            Failure::NetworkFailed => "network_failed",
            Failure::ProcessorFailed => "processor_failed",
            Failure::UnsupportedMode => "unsupported_mode",
            Failure::OutputError => "output_error",
        }
    }

    pub const fn message(self) -> &'static str {
        match self {
            Failure::Usage => "invalid command line",
            Failure::NotAReplay => "the file is not a replay",
            Failure::Corrupt => "the replay fails its integrity checks",
            Failure::NetworkFailed => "the network stream could not be decoded",
            Failure::ProcessorFailed => "the network stream could not be processed",
            Failure::UnsupportedMode => "this game mode is not analyzed",
            Failure::OutputError => "the output could not be written",
        }
    }

    /// The single line written to stderr.
    pub fn to_json(self) -> String {
        serde_json::json!({ "code": self.code(), "message": self.message() }).to_string()
    }

    /// Classifies a parse error by its kind. Its text is dropped.
    pub fn from_parse_error(error: &ParseError) -> Self {
        match error {
            ParseError::NetworkError(_) => Failure::NetworkFailed,
            _ => Failure::Corrupt,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn codes_match_the_contract() {
        let expected = [
            (Failure::Usage, 2, "usage"),
            (Failure::NotAReplay, 10, "not_a_replay"),
            (Failure::Corrupt, 11, "corrupt"),
            (Failure::NetworkFailed, 12, "network_failed"),
            (Failure::ProcessorFailed, 13, "processor_failed"),
            (Failure::UnsupportedMode, 14, "unsupported_mode"),
            (Failure::OutputError, 15, "output_error"),
        ];
        for (failure, exit, code) in expected {
            assert_eq!(failure.exit_code(), exit);
            assert_eq!(failure.code(), code);
        }
    }

    #[test]
    fn the_error_line_is_json_with_only_fixed_text() {
        let line: serde_json::Value = serde_json::from_str(&Failure::Corrupt.to_json()).unwrap();
        assert_eq!(line["code"], "corrupt");
        assert_eq!(line.as_object().unwrap().len(), 2);
    }
}
