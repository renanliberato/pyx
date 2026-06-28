# pyx

> *The pyx is the sacred vessel used to carry the Eucharist wherever it is needed — making the essential portable.*

**pyx** is a language-agnostic bundle generator. Given one or more seed test or source files, it asks the matching language adapter to collect the minimum local context needed to run those files elsewhere, then writes a portable bundle with a standardized `pyx-manifest.json`.

The public workflow is intentionally stable across languages:

```bash
pyx bundle <inputs...>
```

Today pyx supports Dart/Flutter bundles and C# bundles through language adapters.

## Language adapters

`pyx bundle` keeps orchestration language-neutral: it resolves inputs, selects one adapter, creates the output directory, writes a manifest, and optionally verifies the generated bundle. Language-specific behavior stays inside adapters:

- **Dart**: walks Dart imports, resolves local Pub dependencies, and writes a clean Flutter/Dart test bundle.
- **C#**: delegates C# semantic extraction to the `chsarp-class-context` submodule CLI, then assembles the runnable .NET project described by the extractor result.

One bundle uses exactly one language adapter. Mixed Dart/C# inputs are rejected because the initial output formats and run commands are language-specific.

## Usage

### Auto-detect the language

`--language` defaults to `auto`. Auto-detection uses seed extensions:

- `.dart` → Dart adapter
- `.cs` → C# adapter

```bash
# Dart / Flutter
pyx bundle test/leaderboard_test.dart

# C# / .NET
pyx bundle tests/LeaderboardTests.cs
```

### Select a language explicitly

Use `--language auto|dart|csharp` when auto-detection is not specific enough or when a directory contains many file types.

```bash
pyx bundle test/leaderboard_test.dart --language dart
pyx bundle tests/LeaderboardTests.cs --language csharp
```

### Inputs and output directories

Inputs may be files or directories. Directory traversal is language-aware: Dart bundles discover `.dart` files and C# bundles discover `.cs` files.

```bash
# Bundle one file
pyx bundle test/leaderboard_test.dart

# Bundle multiple files of the same language
pyx bundle test/foo_test.dart test/bar_test.dart

# Bundle a directory
pyx bundle lib/modes/ --language dart

# Custom output directory
pyx bundle tests/LeaderboardTests.cs -o /tmp/pyx-csharp-bundle

# From a different project root
pyx --project-root ~/projects/myapp bundle test/foo_test.dart
```

Mixed-language bundles fail before output is written:

```bash
pyx bundle test/foo_test.dart tests/FooTests.cs
# error: mixed Dart and C# inputs are not supported in one bundle
```

### Verify a bundle

Verification is **off by default**. By default, `pyx bundle` only writes files.

Pass `--verify` to run the adapter-provided restore/test commands after the bundle is created:

```bash
pyx bundle test/leaderboard_test.dart --verify
pyx bundle tests/LeaderboardTests.cs --language csharp --verify
```

Verification commands are recorded in `pyx-manifest.json`. A verification failure leaves the bundle on disk, prints the failing command output/status, and exits non-zero.

## Dart bundles

Dart behavior preserves the original pyx workflow: seed files are traced through local Dart imports and relevant local Pub dependencies are copied into a self-contained bundle.

```bash
pyx bundle test/leaderboard_test.dart
cd tmp/pyx-bundle
flutter pub get
flutter test --no-test-assets test/leaderboard_test.dart
```

What the Dart adapter handles:

1. Walks the import graph transitively from seed `.dart` files.
2. Handles relative imports, `package:` imports, `part`/`export` directives, and conditional imports.
3. Resolves `path:` and `git:` dependencies from local project metadata / Pub cache.
4. Copies only imported local dependency files under `bundled_packages/<name>`.
5. Generates a clean `pubspec.yaml` with private path/git references replaced by local bundle paths.
6. Copies optional Dart support files such as `dart_test.yaml` and `analysis_options.yaml` when present.

Private git URLs and private local paths should not appear in the generated Dart `pubspec.yaml`. `pubspec.lock` is intentionally omitted so the target machine resolves a fresh lockfile from the clean pubspec.

## C# bundles

C# bundles are produced through the `chsarp-class-context` extractor submodule. pyx does not parse C# or render project files itself; the extractor owns C# semantics and returns structured bundle instructions.

Example:

```bash
pyx bundle tests/LeaderboardTests.cs --language csharp -o /tmp/leaderboard-csharp-bundle

cd /tmp/leaderboard-csharp-bundle
dotnet restore
dotnet test
```

The C# adapter:

1. Invokes the configured `chsarp-class-context` CLI with the selected seed `.cs` files and project root.
2. Consumes structured JSON from the extractor, including source files, generated project files, run commands, and diagnostics.
3. Copies extractor-selected source files to their requested bundle paths.
4. Writes extractor-generated project files, including the runnable `.csproj`.
5. Records source files, project files, diagnostics, and `dotnet` run commands in `pyx-manifest.json`.

Local C# project references are expected to be flattened into extracted source by the extractor. NuGet and framework references are preserved in the generated project so `dotnet restore` works normally on the target machine.

### C# limitations and diagnostics

C# support depends on the extractor being able to produce a runnable test project. pyx fails rather than emitting a successful partial bundle when extractor diagnostics mark the result as non-runnable.

Unsupported or diagnostic-producing cases can include:

- source-generator, custom MSBuild target, or analyzer behavior that cannot be reproduced in the generated project;
- unresolved project references or files outside the extractor's supported project graph;
- ambiguous test framework or target framework metadata;
- extractor CLI not configured, not present, or returning invalid structured output.

When this happens, pyx prints the extractor diagnostics and exits non-zero. Use those diagnostics to adjust the seed, project metadata, or extractor setup.

## Configuration

Place `.pyx.yaml` at the project root. Configuration is adapter-based: global options live at the top level, while language-specific settings live under their adapter section.

```yaml
# Where to write bundles when -o/--output is not provided.
output_dir: tmp/pyx-bundle

# Default language selection for pyx bundle. Usually auto.
language: auto # auto | dart | csharp

adapters:
  dart:
    # Pub cache root used when resolving git dependencies.
    pub_cache: ~/.pub-cache

    # Package names to hide from logs / generated public metadata.
    redact_packages:
      - my_internal_sdk

    # Extra packages to force-bundle from source.
    bundle_from_source: []

  csharp:
    # Path to the chsarp-class-context submodule CLI.
    extractor: vendor/chsarp-class-context/bin/chsarp-class-context
```

`pyx init` creates a starter config with this adapter-based shape.

## Manifest

Every bundle includes `pyx-manifest.json`. Layouts may differ by language, but the manifest gives automation a stable cross-language place to inspect what was generated.

Standardized fields include:

- `language`: selected adapter, such as `dart` or `csharp`.
- `seeds`: original seed inputs used for the bundle.
- `files`: source/content files copied into the bundle.
- `project_files`: generated or copied project metadata files, such as `pubspec.yaml` or `.csproj`.
- `dependencies`: adapter-provided dependency summary.
- `run_commands`: restore/test commands recommended by the adapter.
- `diagnostics`: warnings or errors reported by the adapter or extractor.

Adapters may add language-specific details, but portable tooling should rely on the standardized fields above.

## What does not get bundled

- Build artifacts such as `.dart_tool/`, `bin/`, `obj/`, and generated caches.
- VCS metadata such as `.git/`.
- Unreachable files outside the adapter-selected context.
- Dart assets or platform directories unless a future adapter explicitly includes them.
