//! `rl-parse`. Commands arrive with step 2 of docs/PLAN.md.

fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

fn main() {
    println!("rl-parse {}", version());
}

#[cfg(test)]
mod tests {
    #[test]
    fn version_is_set() {
        assert!(!super::version().is_empty());
    }
}
