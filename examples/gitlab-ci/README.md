# BOOSTOPT on GitLab CI/CD — sample YAML

Same BOOSTOPT engine as the GitHub Action; GitLab just has different CI syntax. Two forms:

| File | Use it when | What it is |
|---|---|---|
| **`.gitlab-ci.yml`** | you want the simplest thing | A **plain job** — paste it into your project's `.gitlab-ci.yml`. Settings are plain env vars. |
| **`templates/boostopt.yml`** | you want reusable, declared inputs | A **CI/CD Component** — GitLab's analog of GitHub's `action.yml`. Declares `spec: inputs:` (the same entries as the Action) and is `include:`-d with values. |

## Plain job — quickest start
Copy the `boostopt` job from `.gitlab-ci.yml` into your `.gitlab-ci.yml`, make sure the build step emits `compile_commands.json`, done.

## Component — the input-driven form
Publish `templates/boostopt.yml` in a component project, then a consumer writes:
```yaml
include:
  - component: $CI_SERVER_FQDN/boostopt/boostopt-ci/boostopt@v1
    inputs:
      compile_commands: build/compile_commands.json
      mode: suggest
      min_speedup: "3"
```

## How it maps to the GitHub Action
The **entries are the same**, because they all map to `boostopt` CLI flags. Only two syntactic differences:
- **Names:** GitLab inputs use `underscores` (`compile_commands`); GitHub uses `hyphens` (`compile-commands`).
- **Reading them:** GitLab uses `$[[ inputs.name ]]`; GitHub uses `${{ inputs.name }}` / `with:`.

The one truly per-platform bit is **posting the result** to the review UI — GitHub PR comments vs GitLab **Merge Request** notes (different APIs, same `boostopt.json` input). Everything else is identical.

See the full explanation: [`Docs/BOOSTOPT_CI_Action.md`](../../Docs/BOOSTOPT_CI_Action.md) (§ "CI portability"). The GitHub equivalents are in [`../github-action/`](../github-action/).
