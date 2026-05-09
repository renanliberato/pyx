# pyx

> *The pyx is the sacred vessel used to carry the Eucharist wherever it is needed — making the essential portable.*

**pyx** bundles Dart/Flutter test files with their transitive local imports into a self-contained directory. The result can be copied to any machine and run with `flutter pub get && flutter test` — no private repo credentials needed.

## How it works

Given one or more test files, pyx:

1. Walks the import graph (transitively) collecting every local `.dart` file
2. Resolves `path:` and `git:` dependencies from the local pub cache — bundling only the files actually imported
3. Generates a clean `pubspec.yaml` with no private git URLs or repo references — local deps become `path: ./bundled_packages/<name>`
4. Copies everything into the output directory alongside `dart_test.yaml` and `analysis_options.yaml`

Handles: relative imports, `package:` imports, `part`/`export` directives, and conditional imports (`if (dart.library.io) 'other.dart'`).

## Usage

```bash
# Bundle one file
pyx bundle test/leaderboard_test.dart

# Bundle multiple files (single shared traversal)
pyx bundle test/foo_test.dart test/bar_test.dart

# Bundle an entire directory (globs all .dart files recursively)
pyx bundle lib/modes/

# Mix files and directories
pyx bundle lib/modes/ test/modes/ lib/providers/game_provider.dart

# Custom output directory
pyx bundle lib/modes/ -o /tmp/my-bundle

# From a different project root
pyx --project-root ~/projects/myapp bundle test/foo_test.dart

# Create a .pyx.yaml config in the current project
pyx init
```

Then on the target machine:

```bash
cd /path/to/bundle
flutter pub get
flutter test --no-test-assets test/foo_test.dart
```

## Configuration

Place a `.pyx.yaml` at the project root:

```yaml
# Where to write bundles (relative to project root)
output_dir: tmp/pyx-bundle

# pub cache root (default: ~/.pub-cache)
# pub_cache: ~/.pub-cache

# Package names to hide from log output.
# Their source is still bundled and included as a local path: dep,
# but the name is suppressed from pyx's stdout — useful for
# internal/proprietary packages you don't want mentioned in logs.
redact_packages:
  - my_internal_sdk

# Extra packages to force-bundle from source (beyond auto-detected path/git deps).
bundle_from_source: []
```

## What gets bundled

| Source | How it appears in the output pubspec |
|---|---|
| Repo source files (`lib/`, `test/`) | Kept at original relative path |
| `path:` dependencies | `path: ./bundled_packages/<name>` |
| `git:` dependencies | Resolved from `~/.pub-cache/git/`, written as `path: ./bundled_packages/<name>` |
| `pub.dev` dependencies | Kept as-is (`name: ^version`) |

Private git URLs never appear in the output. `pubspec.lock` is intentionally omitted so `flutter pub get` resolves a fresh lockfile from the clean pubspec.

## What does NOT get bundled

- Assets (use `--no-test-assets` when running tests)
- Platform dirs (`android/`, `ios/`, etc.)
- Build artifacts, `.dart_tool/`, `.git/`
- Any file not reachable from the import graph of the seed files
